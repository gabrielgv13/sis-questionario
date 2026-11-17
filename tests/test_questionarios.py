from fastapi.testclient import TestClient
from http_helpers import session_transaction, use_sync_transaction_fixture
import os
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from sis_questionario import bd_exec as db
from sis_questionario.app import create_app


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Configure TEST_DATABASE_URL.')
class QuestionariosTest(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(os.environ['TEST_DATABASE_URL'], row_factory=dict_row)
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.novo_schema()

        @contextmanager
        def conectar_teste():
            with self.conn.transaction():
                yield self.conn

        patcher = patch.object(db, 'conectar', conectar_teste)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.criar_tabelas()
        db.inicializar_banco()
        self.app = create_app()
        use_sync_transaction_fixture(self.app)
        self.client = TestClient(self.app, follow_redirects=False, base_url='https://testserver')
        self.perfil = db.listar_questionarios()[0]

    def novo_schema(self):
        schema = 'teste_' + uuid.uuid4().hex
        self.schema = schema
        self.conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        self.conn.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))

    def quantidade(self, tabela):
        return self.conn.execute(sql.SQL('SELECT COUNT(*) AS total FROM {}').format(
            sql.Identifier(tabela))).fetchone()['total']

    def criar_tabelas(self):
        script = Path(db.__file__).with_name('banco.sql').read_text(encoding='utf-8')
        estrutura = script.split('-- INICIO_TABELAS')[1].split('-- FIM_TABELAS')[0]
        self.conn.execute(estrutura)

    def test_aplicativo_com_apenas_select_e_insert(self):
        permissao = self.conn.execute('''SELECT rolsuper OR rolcreaterole AS permitido
            FROM pg_roles WHERE rolname = current_user''').fetchone()['permitido']
        if not permissao:
            self.skipTest('O administrador de testes precisa poder criar roles temporárias.')
        role = 'teste_client_' + uuid.uuid4().hex
        self.conn.execute(sql.SQL('CREATE ROLE {}').format(sql.Identifier(role)))
        self.conn.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(
            sql.Identifier(self.schema), sql.Identifier(role)))
        self.conn.execute(sql.SQL('''GRANT SELECT, INSERT ON TABLE alunos, envios,
            opcoes, perguntas, questionarios, respostas TO {}''').format(sql.Identifier(role)))
        self.conn.execute(sql.SQL('GRANT USAGE ON ALL SEQUENCES IN SCHEMA {} TO {}').format(
            sql.Identifier(self.schema), sql.Identifier(role)))
        self.conn.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(role)))
        db.inicializar_banco()
        db.cadastrar_questionario('restrito', 'Restrito', [
            {'id': 1, 'pergunta': 'Teste?', 'opcoes': ['A', 'B']},
        ])
        aluno = db.registrar_aluno('Original', 'repetido@example.com')
        self.assertEqual(db.registrar_aluno('Outro nome', 'repetido@example.com'), aluno)
        self.assertEqual(self.conn.execute('SELECT nome FROM alunos WHERE id_aluno = %s', (aluno,)).fetchone()['nome'], 'Original')
        self.cadastrar_participante()
        self.assertEqual(self.client.post('/submit-pesquisa', data=self.formulario()).status_code, 302)
        self.assertEqual(self.quantidade('envios'), 1)
        with self.assertRaises(psycopg.errors.InsufficientPrivilege), self.conn.transaction():
            self.conn.execute('UPDATE alunos SET nome = nome')

    def respostas(self, id_questionario=None):
        questionario = db.carregar_questionario(id_questionario or self.perfil['id_questionario'])
        return {p['id_pergunta']: p['opcoes'][0]['id_opcao'] for p in questionario['perguntas']}

    def cadastrar_participante(self):
        self.client.get('/')
        return self.client.post('/submit-info', data={
            'name': 'Aluno de teste', 'email': 'ALUNO@example.com',
            'questionario_id': self.perfil['id_questionario'],
        })

    def formulario(self):
        with session_transaction(self.client) as sessao:
            token = sessao['token_formulario']
        return {'token_formulario': token,
                **{f'pergunta_{p}': str(o) for p, o in self.respostas().items()}}

    def test_inicializacao_simples_e_idempotente(self):
        db.inicializar_banco()
        tabelas = self.conn.execute('''SELECT table_name FROM information_schema.tables
            WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' ''').fetchall()
        self.assertEqual({t['table_name'] for t in tabelas},
                         {'alunos', 'questionarios', 'perguntas', 'opcoes', 'envios', 'respostas'})
        self.assertEqual(self.quantidade('perguntas'), 11)
        self.assertGreater(self.quantidade('opcoes'), 100)
        self.assertEqual(self.quantidade('questionarios'), 1)
        views = self.conn.execute('SELECT COUNT(*) AS total FROM information_schema.views WHERE table_schema = current_schema()').fetchone()['total']
        self.assertEqual(views, 0)

    def test_fluxo_completo(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/pesquisa-perguntas').status_code, 302)
        self.assertEqual(self.cadastrar_participante().status_code, 302)
        pagina = self.client.get('/pesquisa-perguntas').text
        self.assertEqual(pagina.count('<fieldset '), 11)
        self.assertEqual(pagina.count('<form '), 1)
        dados = self.formulario()
        resposta = self.client.post('/submit-pesquisa', data=dados, follow_redirects=True)
        self.assertEqual(resposta.status_code, 200)
        self.assertIn('foram salvas', resposta.text)
        self.assertEqual(self.quantidade('envios'), 1)
        self.assertEqual(self.quantidade('respostas'), 11)
        self.client.post('/submit-pesquisa', data=dados)
        self.assertEqual(self.quantidade('envios'), 1)
        self.cadastrar_participante()
        self.assertEqual(self.quantidade('alunos'), 1)

    def test_respostas_invalidas_nao_criam_envio(self):
        self.cadastrar_participante()
        dados = self.formulario()
        campos = [k for k in dados if k.startswith('pergunta_')]
        campo = campos[0]
        for alterados in (
            {k: v for k, v in dados.items() if k != campo},
            {**dados, campo: '-1'},
            {**dados, campo: dados[campos[1]]},
            {**dados, campo: 'texto'},
            {**dados, campo: [dados[campo], dados[campo]]},
            {**dados, 'token_formulario': 'errado'},
        ):
            self.assertEqual(self.client.post('/submit-pesquisa', data=alterados).status_code, 400)
            self.assertEqual(self.quantidade('envios'), 0)
            self.assertEqual(self.quantidade('respostas'), 0)

    def test_multiplos_questionarios_sem_versoes(self):
        perguntas = [{'id': 1, 'pergunta': 'Teste?', 'opcoes': ['Sim', 'Não']}]
        outro = db.cadastrar_questionario('satisfacao', 'Satisfação', perguntas)
        perguntas[0]['pergunta'] = 'Alteração no JSON'
        self.assertEqual(db.cadastrar_questionario('satisfacao', 'Satisfação', perguntas), outro)
        self.assertEqual(db.carregar_questionario(outro)['perguntas'][0]['enunciado'], 'Teste?')
        self.assertEqual(len(db.listar_questionarios()), 2)
        aluno = db.registrar_aluno('Teste', 'teste@example.com')
        with self.assertRaises(ValueError):
            db.registrar_envio(aluno, outro, self.respostas(), uuid.uuid4())
        db.registrar_envio(aluno, outro, self.respostas(outro), uuid.uuid4())
        db.registrar_envio(aluno, self.perfil['id_questionario'], self.respostas(), uuid.uuid4())
        totais = self.conn.execute('''SELECT q.titulo, COUNT(e.id_envio) AS total
            FROM questionarios q LEFT JOIN envios e USING (id_questionario)
            GROUP BY q.id_questionario ORDER BY q.titulo''').fetchall()
        self.assertEqual([r['total'] for r in totais], [1, 1])
        self.conn.execute('UPDATE questionarios SET ativo = FALSE WHERE id_questionario = %s', (outro,))
        self.assertIsNone(db.carregar_questionario(outro))
        self.assertEqual(self.quantidade('envios'), 2)

    def test_unicidade_e_chaves_estrangeiras(self):
        aluno = db.registrar_aluno('Teste', 'teste@example.com')
        respostas = self.respostas()
        envio = db.registrar_envio(aluno, self.perfil['id_questionario'], respostas, uuid.uuid4())
        pergunta, opcao = next(iter(respostas.items()))
        with self.assertRaises(psycopg.IntegrityError), self.conn.transaction():
            self.conn.execute('INSERT INTO respostas (id_envio, id_pergunta, id_opcao) VALUES (%s, %s, %s)',
                              (envio, pergunta, opcao))
        with self.assertRaises(psycopg.IntegrityError), self.conn.transaction():
            self.conn.execute('UPDATE respostas SET id_opcao = -1 WHERE id_envio = %s', (envio,))

    def test_falha_reverte_envio_inteiro(self):
        aluno = db.registrar_aluno('Teste', 'teste@example.com')
        respostas = self.respostas()
        bloqueada = list(respostas)[1]
        self.conn.execute(sql.SQL('''CREATE FUNCTION rejeitar_resposta() RETURNS trigger AS $$
            BEGIN IF NEW.id_pergunta = {} THEN RAISE EXCEPTION 'falha de teste'; END IF;
            RETURN NEW; END; $$ LANGUAGE plpgsql''').format(sql.Literal(bloqueada)))
        self.conn.execute('CREATE TRIGGER rejeitar BEFORE INSERT ON respostas FOR EACH ROW EXECUTE FUNCTION rejeitar_resposta()')
        with self.assertRaises(psycopg.Error):
            db.registrar_envio(aluno, self.perfil['id_questionario'], respostas, uuid.uuid4())
        self.assertEqual(self.quantidade('envios'), 0)
        self.assertEqual(self.quantidade('respostas'), 0)

    def test_consultas_de_analise(self):
        aluno = db.registrar_aluno('Teste', 'teste@example.com')
        db.registrar_envio(aluno, self.perfil['id_questionario'], self.respostas(), uuid.uuid4())
        consultas = Path(__file__).resolve().parents[1].joinpath('docs/consultas.md').read_text(encoding='utf-8').split('```sql')[1].split('```')[0]
        for consulta in consultas.split(';'):
            if consulta.strip():
                self.assertTrue(self.conn.execute(consulta).fetchall())

    def test_mesmo_navegador_nao_repete_com_outro_email(self):
        self.cadastrar_participante()
        dados = self.formulario()
        with session_transaction(self.client) as sessao:
            sessao_anterior = dict(sessao)
        self.assertEqual(self.client.post('/submit-pesquisa', data=dados).status_code, 302)
        cookie = next(c for c in self.client.cookies.jar if c.name == 'id_dispositivo')
        self.assertTrue(cookie.has_nonstandard_attr('HttpOnly'))
        self.assertEqual(cookie.get_nonstandard_attr('SameSite').lower(), 'lax')
        self.assertIsNotNone(cookie.expires)
        tentativa = self.client.post('/submit-info', data={
            'name': 'Outra pessoa', 'email': 'outro@example.com',
            'questionario_id': self.perfil['id_questionario'],
        })
        self.assertEqual(tentativa.status_code, 409)
        self.assertIn('Questionário já respondido', tentativa.text)
        self.assertEqual(self.quantidade('alunos'), 1)
        # Uma aba com formulário antigo também recebe bloqueio na gravação.
        with session_transaction(self.client) as sessao:
            sessao.update(sessao_anterior)
        self.assertEqual(self.client.get('/pesquisa-perguntas').status_code, 409)
        self.assertEqual(self.client.post('/submit-pesquisa', data=dados).status_code, 409)
        self.assertEqual(self.quantidade('envios'), 1)
        self.assertEqual(self.quantidade('respostas'), 11)

    def test_cookie_persiste_apos_reiniciar_app(self):
        self.cadastrar_participante()
        self.client.post('/submit-pesquisa', data=self.formulario())
        identificador = self.client.cookies.get('id_dispositivo')
        novo_app = create_app(inicializar=False)
        use_sync_transaction_fixture(novo_app)
        cliente = TestClient(novo_app, follow_redirects=False, base_url='https://testserver')
        cliente.cookies.set('id_dispositivo', identificador)
        cliente.get('/')
        self.assertEqual(cliente.cookies.get('id_dispositivo'), identificador)
        resultado = cliente.post('/submit-info', data={
            'name': 'Teste', 'email': 'teste@example.com',
            'questionario_id': self.perfil['id_questionario'],
        })
        self.assertEqual(resultado.status_code, 409)

    def test_outro_navegador_pode_responder_na_mesma_rede(self):
        self.cadastrar_participante()
        self.client.post('/submit-pesquisa', data=self.formulario())
        outro = TestClient(self.app, follow_redirects=False, base_url='https://testserver')
        outro.get('/')
        self.assertNotEqual(outro.cookies.get('id_dispositivo'),
                            self.client.cookies.get('id_dispositivo'))
        outro.post('/submit-info', data={
            'name': 'Aluno 2', 'email': 'aluno2@example.com',
            'questionario_id': self.perfil['id_questionario'],
        })
        with session_transaction(outro) as sessao:
            token = sessao['token_formulario']
        dados = {'token_formulario': token,
                 **{f'pergunta_{p}': str(o) for p, o in self.respostas().items()}}
        self.assertEqual(outro.post('/submit-pesquisa', data=dados).status_code, 302)
        self.assertEqual(self.quantidade('envios'), 2)

    def test_unicidade_dispositivo_por_questionario_no_banco(self):
        aluno = db.registrar_aluno('Teste', 'teste@example.com')
        dispositivo = uuid.uuid4()
        questionario = self.perfil['id_questionario']
        db.registrar_envio(aluno, questionario, self.respostas(), dispositivo)
        with self.assertRaises(db.EnvioDuplicado):
            db.registrar_envio(aluno, questionario, self.respostas(), dispositivo)
        with self.assertRaises(psycopg.IntegrityError), self.conn.transaction():
            self.conn.execute('''INSERT INTO envios (id_aluno, id_questionario, id_dispositivo)
                VALUES (%s, %s, %s)''', (aluno, questionario, dispositivo))
        outro = db.cadastrar_questionario('outro', 'Outro', [
            {'id': 1, 'pergunta': 'Teste?', 'opcoes': ['A', 'B']},
        ])
        db.registrar_envio(aluno, outro, self.respostas(outro), dispositivo)
        self.assertEqual(self.quantidade('envios'), 2)

    def test_post_sem_cookie_exige_abrir_pagina(self):
        cliente = TestClient(self.app, follow_redirects=False, base_url='https://testserver')
        cliente.get('/')
        cliente.cookies.clear()
        resultado = cliente.post('/submit-info', data={
            'name': 'Teste', 'email': 'teste@example.com',
            'questionario_id': self.perfil['id_questionario'],
        })
        self.assertEqual(resultado.status_code, 400)
        self.assertEqual(self.quantidade('alunos'), 0)

    def test_resultado_persistido_devolutiva_e_privacidade(self):
        self.cadastrar_participante()
        response = self.client.post('/submit-pesquisa', data=self.formulario(), follow_redirects=True)
        self.assertIn('Seu perfil:'.encode(), response.content)
        self.assertIn(b'140 pontos', response.content)
        with session_transaction(self.client) as sessao:
            envio = sessao['envio_id']
        stored = self.conn.execute('SELECT resultado FROM envios WHERE id_envio = %s', (envio,)).fetchone()['resultado']
        self.assertEqual(stored['category'], 'esportes')
        self.assertEqual(stored['version'], 'perfil_v1')
        self.assertIn(b'140 pontos', self.client.get('/concluido').content)
        self.assertIsNone(db.carregar_resultado(envio, uuid.uuid4()))
        other = TestClient(self.app, follow_redirects=False, base_url='https://testserver')
        self.assertEqual(other.get('/concluido').status_code, 302)
        db.configurar_devolutiva(self.perfil['id_questionario'], False)
        self.assertNotIn(b'Seu perfil:', self.client.get('/concluido').content)
        self.criar_tabelas()
        self.assertFalse(db.carregar_questionario(self.perfil['id_questionario'])['exibir_resultado'])
        self.assertEqual(self.conn.execute('SELECT resultado FROM envios WHERE id_envio = %s', (envio,)).fetchone()['resultado'], stored)

    def test_classifica_com_devolutiva_desativada_e_questionario_sem_algoritmo(self):
        db.configurar_devolutiva(self.perfil['id_questionario'], False)
        aluno = db.registrar_aluno('Teste', 'test@example.com')
        envio = db.registrar_envio(aluno, self.perfil['id_questionario'], self.respostas(), uuid.uuid4())
        self.assertEqual(self.conn.execute('SELECT resultado FROM envios WHERE id_envio = %s', (envio,)).fetchone()['resultado']['category'], 'esportes')
        outro = db.cadastrar_questionario('simples', 'Simples', [{'pergunta': 'Teste?', 'opcoes': ['A', 'B']}])
        envio = db.registrar_envio(aluno, outro, self.respostas(outro), uuid.uuid4())
        self.assertIsNone(self.conn.execute('SELECT resultado FROM envios WHERE id_envio = %s', (envio,)).fetchone()['resultado'])
        with self.assertRaises(ValueError):
            db.configurar_devolutiva(outro, True)

    def test_falha_classificacao_nao_grava_envio(self):
        aluno = db.registrar_aluno('Teste', 'test@example.com')
        self.conn.execute('UPDATE perguntas SET enunciado = %s WHERE id_pergunta = %s', ('Alterada', next(iter(self.respostas()))))
        with self.assertRaises(ValueError):
            db.registrar_envio(aluno, self.perfil['id_questionario'], self.respostas(), uuid.uuid4())
        self.assertEqual(self.quantidade('envios'), 0)
        self.assertEqual(self.quantidade('respostas'), 0)

    def test_migracao_habilita_perfil_e_preserva_envios_antigos(self):
        self.conn.execute('ALTER TABLE questionarios DROP COLUMN algoritmo, DROP COLUMN exibir_resultado')
        aluno = db.registrar_aluno('Teste', 'test@example.com')
        self.conn.execute('INSERT INTO envios (id_aluno,id_questionario) VALUES (%s,%s)', (aluno, self.perfil['id_questionario']))
        self.conn.execute('ALTER TABLE envios DROP COLUMN resultado')
        self.criar_tabelas()
        quiz = db.carregar_questionario(self.perfil['id_questionario'])
        self.assertTrue(quiz['exibir_resultado'])
        self.assertEqual(quiz['algoritmo'], 'perfil_v1')
        self.assertIsNone(self.conn.execute('SELECT resultado FROM envios').fetchone()['resultado'])

    def test_import_export_json_armazenado_e_duplicidade(self):
        doc = dict(schema_version=1, codigo='importado', titulo='Importado', ativo=False,
                   algoritmo=None, exibir_resultado=False,
                   perguntas=[dict(enunciado='Pergunta?', opcoes=['B', 'A'])])
        identifier = db.importar_questionario(doc)
        stored = self.conn.execute('SELECT documento FROM questionarios WHERE id_questionario = %s', (identifier,)).fetchone()['documento']
        self.assertEqual(stored, doc)
        self.assertEqual(db.exportar_questionario(identifier), doc)
        before = [self.quantidade(table) for table in ('questionarios','perguntas','opcoes')]
        with self.assertRaises(db.QuestionarioExistente):
            db.importar_questionario(doc)
        self.assertEqual([self.quantidade(table) for table in ('questionarios','perguntas','opcoes')], before)
        self.assertNotIn(identifier, [q['id_questionario'] for q in db.listar_questionarios()])
        doc['codigo'] = 'copia'
        second = db.importar_questionario(doc)
        self.assertEqual(db.exportar_questionario(second), doc)

    def test_exporta_perfil_com_configuracao_atual_e_migra_documentos(self):
        identifier = self.perfil['id_questionario']
        original = db.exportar_questionario(identifier)
        self.assertEqual(len(original['perguntas']), 11)
        self.assertEqual(original['algoritmo'], 'perfil_v1')
        db.configurar_devolutiva(identifier, False)
        self.assertFalse(db.exportar_questionario(identifier)['exibir_resultado'])
        self.assertFalse(self.conn.execute('SELECT documento FROM questionarios WHERE id_questionario = %s', (identifier,)).fetchone()['documento']['exibir_resultado'])
        self.conn.execute('ALTER TABLE questionarios DROP COLUMN documento')
        self.criar_tabelas()
        migrated = db.exportar_questionario(identifier)
        self.assertEqual(migrated['perguntas'], original['perguntas'])
        self.assertFalse(migrated['exibir_resultado'])

    def test_importa_copia_do_perfil_e_classifica_sem_depender_dos_ids(self):
        documento = db.exportar_questionario(self.perfil['id_questionario'])
        documento['codigo'] = 'perfil-copia'
        identifier = db.importar_questionario(documento, db.exportar_algoritmo(self.perfil['id_questionario']))
        self.assertNotEqual(identifier, self.perfil['id_questionario'])
        aluno = db.registrar_aluno('Teste', 'copia@example.com')
        envio = db.registrar_envio(aluno, identifier, self.respostas(identifier), uuid.uuid4())
        resultado = self.conn.execute('SELECT resultado FROM envios WHERE id_envio = %s', (envio,)).fetchone()['resultado']
        self.assertEqual(resultado['scores']['esportes'], 140)
        self.assertEqual(resultado['version'], 'perfil_v1')

    def test_importacao_reverte_tudo_se_insercao_falha(self):
        doc = dict(schema_version=1, codigo='falha', titulo='Falha', ativo=True,
                   algoritmo=None, exibir_resultado=False,
                   perguntas=[dict(enunciado='Pergunta?', opcoes=['A','B'])])
        before = self.quantidade('questionarios')
        self.conn.execute('''CREATE FUNCTION recusar_opcao() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'Falha simulada'; END $$''')
        self.conn.execute('CREATE TRIGGER recusar_opcao BEFORE INSERT ON opcoes FOR EACH ROW EXECUTE FUNCTION recusar_opcao()')
        with self.assertRaises(psycopg.Error):
            db.importar_questionario(doc)
        self.assertEqual(self.quantidade('questionarios'), before)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) AS n FROM questionarios WHERE codigo = 'falha'").fetchone()['n'], 0)

    def test_atualizacao_preserva_envios_sem_identificador(self):
        self.conn.execute('ALTER TABLE envios DROP COLUMN id_dispositivo')
        aluno = db.registrar_aluno('Teste', 'teste@example.com')
        for _ in range(2):
            self.conn.execute('INSERT INTO envios (id_aluno, id_questionario) VALUES (%s, %s)',
                              (aluno, self.perfil['id_questionario']))
        self.criar_tabelas()
        self.assertEqual(self.quantidade('envios'), 2)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) AS total FROM envios WHERE id_dispositivo IS NULL').fetchone()['total'], 2)


if __name__ == '__main__':
    unittest.main()
