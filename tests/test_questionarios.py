import os
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from werkzeug.security import generate_password_hash

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
        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()
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
        self.assertEqual(db.carregar_analise(self.perfil['id_questionario'])['selecionados'], 1)
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
        with self.client.session_transaction() as sessao:
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
        pagina = self.client.get('/pesquisa-perguntas').get_data(as_text=True)
        self.assertEqual(pagina.count('<fieldset '), 11)
        self.assertEqual(pagina.count('<form '), 1)
        dados = self.formulario()
        resposta = self.client.post('/submit-pesquisa', data=dados, follow_redirects=True)
        self.assertEqual(resposta.status_code, 200)
        self.assertIn('foram salvas', resposta.get_data(as_text=True))
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

    def test_analise_filtra_envios_e_preserva_outras_respostas(self):
        aluno = db.registrar_aluno('Teste', 'teste@example.com')
        questionario = db.carregar_questionario(self.perfil['id_questionario'])
        perguntas = questionario['perguntas']
        base = self.respostas()
        jogo = perguntas[10]
        musica = perguntas[3]
        jogo_a, jogo_b = [o['id_opcao'] for o in jogo['opcoes']]
        musica_a, musica_b = [o['id_opcao'] for o in musica['opcoes'][:2]]
        for j, m in ((jogo_a, musica_a), (jogo_b, musica_a), (jogo_b, musica_b)):
            respostas = {**base, jogo['id_pergunta']: j, musica['id_pergunta']: m}
            db.registrar_envio(aluno, questionario['id_questionario'], respostas, uuid.uuid4())
        dados = db.carregar_analise(questionario['id_questionario'], [jogo_b, musica_a])
        self.assertEqual((dados['total'], dados['selecionados']), (3, 1))
        self.assertEqual(len(dados['envios'][0]['respostas']), 11)
        self.assertEqual(dados['questionario']['perguntas'][0]['opcoes'][0]['total'], 1)
        self.assertEqual(dados['questionario']['perguntas'][0]['opcoes'][0]['percentual'], 100)
        self.assertEqual(dados['questionario']['perguntas'][0]['opcoes'][1]['total'], 0)
        self.assertNotIn('nome', dados['envios'][0])
        self.assertEqual(db.carregar_analise(questionario['id_questionario'], [jogo_b])['selecionados'], 2)
        self.assertEqual(db.carregar_analise(questionario['id_questionario'])['selecionados'], 3)
        vazio = db.carregar_analise(questionario['id_questionario'], [jogo_a, musica_b])
        self.assertEqual(vazio['selecionados'], 0)
        self.assertEqual(vazio['envios'], [])
        self.assertEqual(vazio['questionario']['perguntas'][0]['opcoes'][0]['percentual'], 0)
        for filtros in ([jogo_a, jogo_b], [-1], [jogo_a, jogo_a]):
            with self.assertRaises(ValueError):
                db.carregar_analise(questionario['id_questionario'], filtros)
        self.conn.execute('UPDATE questionarios SET ativo = FALSE WHERE id_questionario = %s',
                          (questionario['id_questionario'],))
        self.assertIsNotNone(db.carregar_analise(questionario['id_questionario']))
        self.app.config['ADMIN_PASSWORD_HASH'] = generate_password_hash('senha-de-teste')
        self.client.get('/admin/login')
        with self.client.session_transaction() as sessao:
            token = sessao['token_admin']
        self.assertEqual(self.client.post('/admin/login', data={
            'senha': 'senha-de-teste', 'token_admin': token}).status_code, 302)
        pagina = self.client.get('/analise', query_string={
            'questionario': questionario['id_questionario'], 'opcao': [jogo_b, musica_a]})
        self.assertEqual(pagina.status_code, 200)
        html = pagina.get_data(as_text=True)
        self.assertIn('de 3 envios', html)
        self.assertIn(perguntas[0]['enunciado'], html)
        self.assertIn('100,0%', html)
        self.assertNotIn('teste@example.com', html)

    def test_analise_paginacao_e_isolamento_de_questionarios(self):
        outro = db.cadastrar_questionario('outro', 'Outro', [
            {'pergunta': 'Teste?', 'opcoes': ['Sim', 'Não']}])
        aluno = db.registrar_aluno('Teste', 'teste@example.com')
        for _ in range(51):
            db.registrar_envio(aluno, outro, self.respostas(outro), uuid.uuid4())
        dados = db.carregar_analise(outro, pagina=999)
        self.assertEqual((dados['pagina'], dados['paginas']), (2, 2))
        self.assertEqual(len(dados['envios']), 1)
        primeira = db.carregar_analise(outro, pagina=-1)
        self.assertEqual(len(primeira['envios']), 50)
        self.assertGreater(primeira['envios'][-1]['id_envio'], dados['envios'][0]['id_envio'])
        self.assertEqual(db.carregar_analise(self.perfil['id_questionario'])['total'], 0)
        with self.assertRaises(ValueError):
            db.carregar_analise(outro, list(self.respostas().values())[:1])

    def test_mesmo_navegador_nao_repete_com_outro_email(self):
        self.cadastrar_participante()
        dados = self.formulario()
        with self.client.session_transaction() as sessao:
            sessao_anterior = dict(sessao)
        self.assertEqual(self.client.post('/submit-pesquisa', data=dados).status_code, 302)
        cookie = self.client.get_cookie('id_dispositivo')
        self.assertTrue(cookie.http_only)
        self.assertEqual(cookie.same_site, 'Lax')
        self.assertIsNotNone(cookie.expires)
        tentativa = self.client.post('/submit-info', data={
            'name': 'Outra pessoa', 'email': 'outro@example.com',
            'questionario_id': self.perfil['id_questionario'],
        })
        self.assertEqual(tentativa.status_code, 409)
        self.assertIn('Questionário já respondido', tentativa.get_data(as_text=True))
        self.assertEqual(self.quantidade('alunos'), 1)
        # Uma aba com formulário antigo também recebe bloqueio na gravação.
        with self.client.session_transaction() as sessao:
            sessao.update(sessao_anterior)
        self.assertEqual(self.client.get('/pesquisa-perguntas').status_code, 409)
        self.assertEqual(self.client.post('/submit-pesquisa', data=dados).status_code, 409)
        self.assertEqual(self.quantidade('envios'), 1)
        self.assertEqual(self.quantidade('respostas'), 11)

    def test_cookie_persiste_apos_reiniciar_app(self):
        self.cadastrar_participante()
        self.client.post('/submit-pesquisa', data=self.formulario())
        identificador = self.client.get_cookie('id_dispositivo').value
        novo_app = create_app(inicializar=False)
        novo_app.testing = True
        cliente = novo_app.test_client()
        cliente.set_cookie('id_dispositivo', identificador)
        cliente.get('/')
        self.assertEqual(cliente.get_cookie('id_dispositivo').value, identificador)
        resultado = cliente.post('/submit-info', data={
            'name': 'Teste', 'email': 'teste@example.com',
            'questionario_id': self.perfil['id_questionario'],
        })
        self.assertEqual(resultado.status_code, 409)

    def test_outro_navegador_pode_responder_na_mesma_rede(self):
        self.cadastrar_participante()
        self.client.post('/submit-pesquisa', data=self.formulario())
        outro = self.app.test_client()
        outro.get('/')
        self.assertNotEqual(outro.get_cookie('id_dispositivo').value,
                            self.client.get_cookie('id_dispositivo').value)
        outro.post('/submit-info', data={
            'name': 'Aluno 2', 'email': 'aluno2@example.com',
            'questionario_id': self.perfil['id_questionario'],
        })
        with outro.session_transaction() as sessao:
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
        cliente = self.app.test_client(use_cookies=False)
        cliente.get('/')
        resultado = cliente.post('/submit-info', data={
            'name': 'Teste', 'email': 'teste@example.com',
            'questionario_id': self.perfil['id_questionario'],
        })
        self.assertEqual(resultado.status_code, 400)
        self.assertEqual(self.quantidade('alunos'), 0)

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
