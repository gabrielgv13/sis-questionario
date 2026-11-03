import os
import re
import tempfile
import unittest
import uuid
import runpy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from sis_questionario import bd_exec as db
from sis_questionario.app import create_app
from sis_questionario.config import conexao_banco
from sis_questionario.provision import preparar_senha, provisionar, TABLES


class DeploymentConfigurationTest(unittest.TestCase):
    def test_web_exec_removes_provisioning_credentials(self):
        environment = {'DB_USER': 'sis_app', 'DB_PASSWORD_FILE': '', 'DB_PASSWORD': 'x' * 32,
                       'SECRET_KEY': 's' * 32, 'ADMIN_PASSWORD': 'admin-test',
                       'DB_ADMIN_USER': 'sis_owner', 'DB_ADMIN_PASSWORD': 'private'}
        with patch.dict(os.environ, environment), patch('os.execvp') as execute:
            runpy.run_path(str(Path(__file__).resolve().parents[1] / 'images/common/entrypoint.py'))
            self.assertNotIn('DB_ADMIN_PASSWORD', os.environ)
            self.assertNotIn('DB_ADMIN_USER', os.environ)
            self.assertEqual(execute.call_args.args[0], 'gunicorn')

    def test_generated_password_is_persistent_and_readable_by_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'password'
            with patch.dict(os.environ, {'DB_PASSWORD_FILE': str(path)}):
                first = preparar_senha()
                self.assertGreaterEqual(len(first), 48)
                self.assertEqual(preparar_senha(), first)
                self.assertEqual(conexao_banco()['password'], first)

    def test_admin_password_and_https_cookie(self):
        with patch.dict(os.environ, {'ADMIN_PASSWORD': 'deployment-test-password',
                                   'ADMIN_PASSWORD_HASH': '', 'COOKIE_SECURE': '1',
                                   'TRUST_PROXY': '1'}):
            client = create_app().test_client()
            page = client.get('/admin/login', headers={'X-Forwarded-Proto': 'https'})
            self.assertTrue(all('Secure' in c for c in page.headers.getlist('Set-Cookie')))
            token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data)[1].decode()
            response = client.post('/admin/login', data={'csrf_token': token,
                                                       'password': 'deployment-test-password'})
            self.assertEqual(response.status_code, 302)

    def test_health_does_not_expose_database_failure(self):
        with patch.object(db, 'conectar', side_effect=psycopg.OperationalError('private details')):
            response = create_app().test_client().get('/healthz')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json, {'status': 'unavailable'})


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Configure TEST_DATABASE_URL.')
class ProvisionDatabaseTest(unittest.TestCase):
    """Bancos descartáveis: exige CREATEDB e CREATEROLE no servidor de teste."""
    def setUp(self):
        self.admin = psycopg.connect(os.environ['TEST_DATABASE_URL'], autocommit=True)
        self.addCleanup(self.admin.close)
        suffix = uuid.uuid4().hex
        self.database = 'deploy_test_' + suffix
        self.role = 'app_test_' + suffix
        self.admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(self.database)))
        self.addCleanup(self.cleanup_database)
        options = conninfo_to_dict(os.environ['TEST_DATABASE_URL'])
        self.environment = {
            'DB_HOST': options.get('host', 'localhost'), 'DB_PORT': options.get('port', '5432'),
            'DB_NAME': self.database, 'DB_USER': self.role,
            'DB_PASSWORD': uuid.uuid4().hex + uuid.uuid4().hex, 'DB_PASSWORD_FILE': '',
            'DB_ADMIN_USER': options['user'], 'DB_ADMIN_PASSWORD': options['password'],
            'DB_SSLMODE': options.get('sslmode', 'prefer'), 'SEED_PROFILE': '0',
            'ADMIN_PASSWORD': 'test-admin-password', 'ADMIN_PASSWORD_HASH': '',
            'COOKIE_SECURE': '0', 'TRUST_PROXY': '0', 'SECRET_KEY': uuid.uuid4().hex,
        }
        env = patch.dict(os.environ, self.environment)
        env.start()
        self.addCleanup(env.stop)

    def cleanup_database(self):
        self.admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(self.database)))
        self.admin.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(self.role)))

    def count(self, table):
        with db.conectar() as conn:
            return conn.execute(sql.SQL('SELECT COUNT(*) FROM {}').format(sql.Identifier(table))).fetchone()['count']

    def test_clean_profile_submission_and_reprovision_preserve_data(self):
        provisionar()
        self.assertTrue(all(self.count(table) == 0 for table in TABLES))
        with patch.dict(os.environ, {'SEED_PROFILE': '1'}):
            provisionar()
            provisionar()
        self.assertEqual(self.count('questionarios'), 1)
        self.assertEqual(self.count('perguntas'), 11)
        self.assertEqual(self.count('opcoes'), 120)
        self.assertTrue(all(self.count(t) == 0 for t in ('alunos', 'envios', 'respostas')))
        quiz = db.carregar_questionario(db.listar_questionarios()[0]['id_questionario'])
        client = create_app().test_client()
        self.assertEqual(client.get('/healthz').status_code, 200)
        self.assertEqual(client.get('/').status_code, 200)
        malicious = "Aluno'); DROP TABLE alunos; --"
        response = client.post('/submit-info', data={'name': malicious, 'email': 'deploy@example.com',
                                                    'questionario_id': quiz['id_questionario']})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.get('/pesquisa-perguntas').status_code, 200)
        with client.session_transaction() as session:
            token = session['token_formulario']
        answers = {'pergunta_' + str(p['id_pergunta']): str(p['opcoes'][0]['id_opcao']) for p in quiz['perguntas']}
        answers['token_formulario'] = token
        self.assertIn(client.post('/submit-pesquisa', data=answers).status_code, (200, 302))
        self.assertEqual(self.count('envios'), 1)
        provisionar()
        self.assertEqual(self.count('envios'), 1)
        with db.conectar() as conn:
            self.assertEqual(conn.execute('SELECT nome FROM alunos').fetchone()['nome'], malicious)
        # Fluxo administrativo também deve funcionar com a conta restrita.
        page = client.get('/admin/login')
        csrf = re.search(rb'name="csrf_token" value="([^"]+)"', page.data)[1].decode()
        self.assertEqual(client.post('/admin/login', data={'csrf_token': csrf, 'password': 'test-admin-password'}).status_code, 302)
        self.assertEqual(client.get('/admin/analise').status_code, 200)
        db.configurar_devolutiva(quiz['id_questionario'], False)

    def test_privileges_are_restricted(self):
        provisionar()
        commands = ['CREATE TABLE public.forbidden (id int)', 'ALTER TABLE public.alunos ADD COLUMN forbidden int',
                    'DROP TABLE public.respostas', 'TRUNCATE public.alunos CASCADE',
                    'DELETE FROM public.alunos', 'UPDATE public.questionarios SET titulo = \'forbidden\'',
                    'CREATE ROLE forbidden_deploy_role']
        for command in commands:
            with self.subTest(command=command), db.conectar() as conn:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    conn.execute(command)
                conn.rollback()

    def test_concurrent_provisioning_is_serialized(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(provisionar) for _ in range(2)]
            for future in futures:
                future.result(timeout=40)
        self.assertTrue(all(self.count(table) == 0 for table in TABLES))

    def test_wrong_password_does_not_rotate(self):
        provisionar()
        wrong = uuid.uuid4().hex
        try:
            with psycopg.connect(**{**conexao_banco(), 'password': wrong}):
                pass
        except psycopg.OperationalError:
            pass
        else:
            self.skipTest('Servidor de teste aceita conexão sem verificar senha (trust).')
        with patch.dict(os.environ, {'DB_PASSWORD': wrong}):
            with self.assertRaisesRegex(ValueError, 'senha'):
                provisionar()
        with db.conectar() as conn:
            self.assertEqual(conn.execute('SELECT 1').fetchone()['?column?'], 1)
