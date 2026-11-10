"""HTTP regression coverage without requiring a PostgreSQL server."""
import asyncio
import re
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from http_helpers import session_transaction
from sis_questionario.bd_async import AsyncDatabase as db
from sis_questionario.app import create_app
from sis_questionario.questionario_json import MAX_BYTES


class ParticipantRoutesTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = TestClient(self.app, base_url='https://testserver', follow_redirects=False)
        self.addCleanup(self.client.close)
        self.quiz = dict(id_questionario=1, titulo='Teste', perguntas=[
            dict(id_pergunta=2, enunciado='Escolha', opcoes=[dict(id_opcao=3, texto='Sim')])])
        for name, result in [('listar_questionarios', [self.quiz]),
                             ('carregar_questionario', self.quiz),
                             ('dispositivo_ja_respondeu', False), ('registrar_aluno', 4)]:
            mock = patch.object(db, name, return_value=result)
            mock.start()
            self.addCleanup(mock.stop)

    def start_questionnaire(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        response = self.client.post('/submit-info', data={
            'name': ' Aluno ', 'email': ' ALUNO@EXAMPLE.COM ', 'questionario_id': '1'})
        self.assertEqual(response.status_code, 302)
        db.registrar_aluno.assert_called_once_with('Aluno', 'aluno@example.com')
        page = self.client.get('/pesquisa-perguntas')
        self.assertEqual(page.status_code, 200)
        return re.search(r'name="token_formulario" value="([^"]+)"', page.text)[1]

    def test_full_participant_flow_and_private_completion(self):
        token = self.start_questionnaire()
        with patch.object(db, 'registrar_envio', return_value=5) as save:
            response = self.client.post('/submit-pesquisa', data={
                'token_formulario': token, 'pergunta_2': '3'})
        self.assertEqual(response.status_code, 302)
        save.assert_called_once_with(4, 1, {2: 3}, self.client.cookies.get('id_dispositivo'))
        with patch.object(db, 'carregar_resultado', return_value=None) as result:
            page = self.client.get('/concluido')
        self.assertEqual(page.status_code, 200)
        self.assertIn('foram salvas', page.text)
        self.assertEqual(page.headers['Cache-Control'], 'no-store')
        result.assert_called_once_with(5, self.client.cookies.get('id_dispositivo'))
        with session_transaction(self.client) as session:
            self.assertNotIn('token_formulario', session)
            self.assertNotIn('questionario_id', session)

    def test_bad_csrf_and_repeated_answers_do_not_write(self):
        token = self.start_questionnaire()
        with patch.object(db, 'registrar_envio') as save:
            for data in [{'token_formulario': 'wrong', 'pergunta_2': '3'},
                         {'token_formulario': token, 'pergunta_2': ['3', '3']},
                         {'token_formulario': token, 'pergunta_bad': '3'}]:
                self.assertEqual(self.client.post('/submit-pesquisa', data=data).status_code, 400)
            save.assert_not_called()

    def test_duplicate_submission_is_conflict(self):
        token = self.start_questionnaire()
        with patch.object(db, 'registrar_envio', side_effect=db.EnvioDuplicado):
            response = self.client.post('/submit-pesquisa', data={
                'token_formulario': token, 'pergunta_2': '3'})
        self.assertEqual(response.status_code, 409)

    def test_cookie_errors_static_files_and_missing_page(self):
        response = self.client.post('/submit-info', data={})
        self.assertEqual(response.status_code, 400)
        self.assertIn('400', response.text)
        self.assertIn('habilite os cookies', response.text)
        db.registrar_aluno.assert_not_called()
        self.assertEqual(self.client.get('/static/css/app.css').status_code, 200)
        missing = self.client.get('/missing')
        self.assertEqual(missing.status_code, 404)
        self.assertIn('404', missing.text)

    def test_upload_limit_and_malformed_json(self):
        self.client.get('/')
        with session_transaction(self.client) as session:
            session.update(admin_authenticated=True, admin_csrf='token')
        headers = {'X-CSRF-Token': 'token'}
        response = self.client.post('/admin/api/questionnaires/import', headers=headers,
                                    content=b'x' * (2 * MAX_BYTES + 65537))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        response = self.client.post('/admin/api/results', headers={
            **headers, 'Content-Type': 'application/json'}, content=b'{')
        self.assertEqual(response.status_code, 400)


class AsyncConcurrencyTest(unittest.IsolatedAsyncioTestCase):
    async def test_database_wait_does_not_block_other_requests(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow_listing():
            entered.set()
            await asyncio.wait_for(release.wait(), 5)
            return []

        app = create_app()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://testserver') as client:
            with patch.object(db, 'listar_questionarios', side_effect=slow_listing):
                slow = asyncio.create_task(client.get('/'))
                try:
                    await asyncio.wait_for(entered.wait(), 2)
                    response = await asyncio.wait_for(client.get('/missing'), timeout=2)
                    self.assertEqual(response.status_code, 404)
                finally:
                    release.set()
                    await slow
