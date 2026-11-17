"""Real async PostgreSQL transactions, pool recovery and HTTP integration."""
import asyncio
import os
import unittest
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from sis_questionario.app import create_app
from sis_questionario.async_pool import get_database
from sis_questionario.bd_async import AsyncDatabase
from sis_questionario.bd_exec import EnvioDuplicado
from sis_questionario.server import loop_factory


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Configure TEST_DATABASE_URL.')
class AsyncDatabaseTest(unittest.IsolatedAsyncioTestCase):
    loop_factory = staticmethod(loop_factory)

    async def asyncSetUp(self):
        self.schema = 'async_test_' + uuid4().hex
        self.owner = await psycopg.AsyncConnection.connect(os.environ['TEST_DATABASE_URL'], autocommit=True)
        self.addAsyncCleanup(self.owner.close)
        await self.owner.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.addAsyncCleanup(self.drop_schema)
        await self.owner.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(self.schema)))
        script = Path('src/sis_questionario/banco.sql').read_text(encoding='utf-8')
        await self.owner.execute(script.split('-- INICIO_TABELAS')[1].split('-- FIM_TABELAS')[0])
        self.pool = AsyncConnectionPool(
            os.environ['TEST_DATABASE_URL'], min_size=0, max_size=2, timeout=.3, open=False,
            kwargs={'row_factory': dict_row, 'options': '-c search_path=' + self.schema},
            check=AsyncConnectionPool.check_connection,
        )
        await self.pool.open()
        self.addAsyncCleanup(self.pool.close)
        self.db = AsyncDatabase(self.pool)
        self.quiz = await self.db.cadastrar_questionario('simple', 'Simple', [
            dict(pergunta='First?', opcoes=['A', 'B']), dict(pergunta='Second?', opcoes=['C', 'D'])])
        self.student = await self.db.registrar_aluno('Test', 'test@example.com')
        quiz = await self.db.carregar_questionario(self.quiz)
        self.answers = {q['id_pergunta']: q['opcoes'][0]['id_opcao'] for q in quiz['perguntas']}

    async def drop_schema(self):
        await self.owner.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))

    async def test_commit_duplicate_and_aggregate_snapshot(self):
        device = uuid4()
        await self.db.registrar_envio(self.student, self.quiz, self.answers, device)
        self.assertTrue(await self.db.dispositivo_ja_respondeu(device, self.quiz))
        with self.assertRaises(EnvioDuplicado):
            await self.db.registrar_envio(self.student, self.quiz, self.answers, device)
        result = await self.db.resultados_questionario(self.quiz, {})
        self.assertEqual((result['total'], result['matching']), (1, 1))
        self.assertEqual([chart['base'] for chart in result['charts']], [1, 1])

    async def test_mid_submission_failure_rolls_back_all_writes(self):
        await self.owner.execute('''CREATE FUNCTION reject_answer() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION 'test failure'; END; $$ LANGUAGE plpgsql''')
        await self.owner.execute('''CREATE TRIGGER reject_answer BEFORE INSERT ON respostas
            FOR EACH ROW EXECUTE FUNCTION reject_answer()''')
        with self.assertRaises(psycopg.Error):
            await self.db.registrar_envio(self.student, self.quiz, self.answers, uuid4())
        async with self.pool.connection() as conn:
            count = await (await conn.execute('SELECT COUNT(*) AS n FROM envios')).fetchone()
            self.assertEqual(count['n'], 0)
        await self.owner.execute('DROP TRIGGER reject_answer ON respostas')
        await self.db.registrar_envio(self.student, self.quiz, self.answers, uuid4())

    async def test_cancellation_returns_connection_and_rolls_back(self):
        entered = asyncio.Event()

        async def transaction():
            async with self.pool.connection() as conn:
                await conn.execute("INSERT INTO alunos (nome, email) VALUES ('Cancel', 'cancel@example.com')")
                entered.set()
                await conn.execute('SELECT pg_sleep(20)')

        task = asyncio.create_task(transaction())
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        async with self.pool.connection() as conn:
            row = await (await conn.execute("SELECT COUNT(*) AS n FROM alunos WHERE email = 'cancel@example.com'")).fetchone()
            self.assertEqual(row['n'], 0)
        await self.db.check_health()

    async def test_pool_exhaustion_and_recovery(self):
        async with self.pool.connection(), self.pool.connection():
            with self.assertRaises(PoolTimeout):
                async with self.pool.connection():
                    self.fail('Pool exceeded max_size')
        await self.db.check_health()

    async def test_http_participant_flow_uses_async_database(self):
        import re
        app = create_app()
        app.dependency_overrides[get_database] = lambda: self.db
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://testserver', follow_redirects=False) as client:
            self.assertEqual((await client.get('/healthz')).status_code, 200)
            self.assertEqual((await client.get('/')).status_code, 200)
            response = await client.post('/submit-info', data={
                'name': 'HTTP', 'email': 'http@example.com', 'questionario_id': str(self.quiz)})
            self.assertEqual(response.status_code, 302)
            page = await client.get('/pesquisa-perguntas')
            token = re.search(r'name="token_formulario" value="([^"]+)"', page.text)[1]
            response = await client.post('/submit-pesquisa', data={
                'token_formulario': token, **{'pergunta_' + str(k): str(v) for k, v in self.answers.items()}})
            self.assertEqual(response.status_code, 302)
            self.assertEqual((await client.get('/concluido')).status_code, 200)

    async def test_profile_import_export_and_settings(self):
        import json
        document = json.loads(Path('docs/questionario_perfil.json').read_text(encoding='utf-8'))
        from sis_questionario.perfis import REGRAS
        identifier = await self.db.importar_questionario(document, REGRAS)
        exported = await self.db.exportar_questionario(identifier)
        self.assertEqual(exported['perguntas'], document['perguntas'])
        await self.db.configurar_devolutiva(identifier, False)
        self.assertFalse((await self.db.exportar_questionario(identifier))['exibir_resultado'])
        self.assertEqual(len(await self.db.listar_questionarios_admin()), 2)

    async def test_admin_exports_use_async_query_and_release_connection(self):
        import re
        from werkzeug.security import generate_password_hash
        app = create_app()
        app.state.settings['ADMIN_PASSWORD_HASH'] = generate_password_hash('test-password')
        app.dependency_overrides[get_database] = lambda: self.db
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://testserver', follow_redirects=False) as client:
            page = await client.get('/admin/login')
            token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
            response = await client.post('/admin/login', data={'csrf_token': token, 'password': 'test-password'})
            self.assertEqual(response.status_code, 302)
            page = await client.get('/admin/analise')
            token = re.search(r'data-token="([^"]+)"', page.text)[1]
            for kind in ('csv', 'json', 'pdf'):
                response = await client.post('/admin/api/export', headers={'X-CSRF-Token': token},
                    json={'quiz_id': self.quiz, 'format': kind, 'mode': 'simple'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertIn('attachment', response.headers['Content-Disposition'])
                self.assertEqual(self.pool.get_stats()['pool_available'], self.pool.get_stats()['pool_size'])

    async def test_custom_algorithm_is_persisted_and_used_by_results_and_charts(self):
        from test_algoritmo_json import exemplos
        quiz, rules = exemplos()
        with self.assertRaises(ValueError):
            await self.db.importar_questionario(quiz)
        self.assertEqual(len(await self.db.listar_questionarios_admin()), 1)
        identifier = await self.db.importar_questionario(quiz, rules)
        self.assertEqual(await self.db.exportar_algoritmo(identifier), rules)
        stored = await self.db.carregar_questionario(identifier)
        self.assertEqual(stored['regras_algoritmo'], rules)
        self.assertEqual(await AsyncDatabase(self.pool).exportar_algoritmo(identifier), rules)
        answers = {q['id_pergunta']: q['opcoes'][0]['id_opcao'] for q in stored['perguntas']}
        device = uuid4()
        submission = await self.db.registrar_envio(self.student, identifier, answers, device)
        result = await self.db.carregar_resultado(submission, device)
        self.assertEqual(result['category'], 'perfil_a')
        self.assertEqual(result['scores'], {'perfil_a': 40, 'perfil_b': -10})
        self.assertEqual(result['profiles'], rules['profiles'])
        charts = await self.db.resultados_questionario(identifier, {}, ['perfil_a'])
        self.assertEqual(charts['matching'], 1)
        self.assertEqual(charts['charts'][0]['options'][0]['label'], 'Nome do perfil A')
        with self.assertRaises(EnvioDuplicado):
            await self.db.registrar_envio(self.student, identifier, answers, device)
