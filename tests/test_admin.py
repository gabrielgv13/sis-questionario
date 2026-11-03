import os
import re
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


class AdminAccessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = generate_password_hash('test-admin-password')

    def setUp(self):
        env = patch.dict(os.environ, {'ADMIN_PASSWORD_HASH': self.password_hash})
        env.start()
        self.addCleanup(env.stop)
        self.app = create_app(inicializar=False)
        self.app.testing = True
        self.client = self.app.test_client()

    def token(self):
        page = self.client.get('/admin/login')
        return re.search(rb'name="csrf_token" value="([^"]+)"', page.data)[1].decode()

    def login(self):
        return self.client.post('/admin/login', data={
            'csrf_token': self.token(), 'password': 'test-admin-password'})

    def test_unauthenticated_access(self):
        self.assertEqual(self.client.get('/admin').status_code, 302)
        self.assertEqual(self.client.get('/admin/analise').status_code, 302)
        self.assertEqual(self.client.get('/admin/questionarios').status_code, 302)
        self.assertEqual(self.client.post('/admin/api/results', json={'quiz_id': 1}).status_code, 401)

    def test_admin_home_navigation_and_management_preview(self):
        response = self.login()
        self.assertTrue(response.location.endswith('/admin/'))
        with patch.object(db, 'listar_questionarios_admin') as listing:
            home = self.client.get('/admin')
            listing.assert_not_called()
        self.assertIn(b'/admin/analise', home.data)
        self.assertIn(b'/admin/questionarios', home.data)
        questions = [dict(id_questionario=1, titulo='Perfil <teste>', codigo='perfil', ativo=True,
                          algoritmo='perfil_v1', exibir_resultado=False)]
        with patch.object(db, 'listar_questionarios_admin', return_value=questions):
            analysis = self.client.get('/admin/analise')
            management = self.client.get('/admin/questionarios')
        self.assertEqual(analysis.status_code, 200)
        self.assertIn(b'id="admin-dashboard"', analysis.data)
        self.assertEqual(management.status_code, 200)
        self.assertIn(b'Perfil &lt;teste&gt;', management.data)
        self.assertIn(b'id="management-confirm" class="admin-button" type="button" disabled', management.data)
        self.assertIn(b'data-management-action="import"', management.data)
        self.assertIn(b'data-management-action="export"', management.data)
        self.assertIn(b'data-management-action="delete"', management.data)
        self.assertNotIn(b'id="admin-dashboard"', management.data)
        self.assertEqual(management.headers['Cache-Control'], 'no-store')

    def test_login_requires_configuration_correct_password_and_csrf(self):
        self.assertEqual(self.client.post('/admin/login', data={'password': 'test-admin-password'}).status_code, 400)
        self.client.post('/admin/login', data={'csrf_token': self.token(), 'password': 'wrong'})
        with self.client.session_transaction() as session:
            self.assertFalse(session.get('admin_authenticated'))
        with patch.dict(self.app.config, {'ADMIN_PASSWORD_HASH': ''}):
            self.assertEqual(self.client.get('/admin/login').status_code, 503)
        self.assertEqual(self.login().status_code, 302)

    def test_dashboard_api_validation_and_logout(self):
        self.login()
        with patch.object(db, 'listar_questionarios_admin', return_value=[]):
            page = self.client.get('/admin')
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers['Cache-Control'], 'no-store')
        with self.client.session_transaction() as session:
            token = session['admin_csrf']
        headers = {'X-CSRF-Token': token}
        self.assertEqual(self.client.post('/admin/api/results', json={'quiz_id': 1}).status_code, 400)
        for payload in [[], {'quiz_id': True}, {'quiz_id': 1, 'filters': []}]:
            self.assertEqual(self.client.post('/admin/api/results', json=payload, headers=headers).status_code, 400)
        with patch.object(db, 'resultados_questionario', return_value={'total': 2, 'charts': []}) as query:
            response = self.client.post('/admin/api/results', json={'quiz_id': 1}, headers=headers)
            self.assertEqual(response.json['total'], 2)
            query.assert_called_once_with(1, {})
        self.assertEqual(self.client.get('/admin/logout').status_code, 405)
        self.assertEqual(self.client.post('/admin/logout', data={'csrf_token': token}).status_code, 302)
        self.assertEqual(self.client.post('/admin/api/results', json={'quiz_id': 1}).status_code, 401)


    def test_settings_require_authentication_csrf_and_boolean(self):
        self.client.get('/admin/login')
        self.assertEqual(self.client.post('/admin/api/settings', json={}).status_code, 401)
        self.login()
        with self.client.session_transaction() as session:
            headers = {'X-CSRF-Token': session['admin_csrf']}
        payload = {'quiz_id': 1, 'show_result': False}
        self.assertEqual(self.client.post('/admin/api/settings', json=payload).status_code, 400)
        self.assertEqual(self.client.post('/admin/api/settings', json={'quiz_id': 1, 'show_result': 'false'}, headers=headers).status_code, 400)
        with patch.object(db, 'configurar_devolutiva') as configure:
            response = self.client.post('/admin/api/settings', json=payload, headers=headers)
            self.assertEqual(response.status_code, 200)
            configure.assert_called_once_with(1, False)
        with patch.object(db, 'configurar_devolutiva', side_effect=ValueError('Sem algoritmo')):
            self.assertEqual(self.client.post('/admin/api/settings', json=payload, headers=headers).status_code, 400)


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Configure TEST_DATABASE_URL.')
class AdminAggregationTest(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(os.environ['TEST_DATABASE_URL'], row_factory=dict_row, autocommit=True)
        self.addCleanup(self.conn.close)
        self.schema = 'admin_test_' + uuid.uuid4().hex
        self.conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.addCleanup(self.cleanup_schema)
        self.conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(self.schema)))
        script = Path(db.__file__).with_name('banco.sql').read_text(encoding='utf-8')
        self.conn.execute(script.split('-- INICIO_TABELAS')[1].split('-- FIM_TABELAS')[0])
        self.conn.execute("INSERT INTO alunos VALUES (1, 'Test', 'test@example.com')")
        self.conn.execute("INSERT INTO questionarios VALUES (1, 'one', 'One', true), (2, 'two', 'Two', false)")
        self.conn.execute("INSERT INTO perguntas VALUES (1, 1, 'Course?', 1), (2, 1, 'Schedule?', 2), (3, 2, 'Other?', 1)")
        self.conn.execute("INSERT INTO opcoes VALUES (1, 1, 'Engineering', 1), (2, 1, 'Art', 2), (3, 1, 'Zero', 3), (4, 2, 'Evening', 1), (5, 2, 'Morning', 2), (6, 2, 'Zero', 3), (7, 3, 'Other', 1)")
        # The same participant has multiple submissions: filtering must join by submission.
        self.conn.execute('INSERT INTO envios (id_envio, id_aluno, id_questionario) VALUES (1,1,1),(2,1,1),(3,1,1),(4,1,2)')
        self.conn.execute('''INSERT INTO respostas (id_envio,id_pergunta,id_opcao) VALUES
            (1,1,1),(1,2,4),(2,1,1),(2,2,5),(3,1,2),(3,2,5),(4,3,7)''')
        self.conn.autocommit = False

        @contextmanager
        def connection():
            with self.conn.transaction():
                yield self.conn
        patcher = patch.object(db, 'conectar', connection)
        patcher.start()
        self.addCleanup(patcher.stop)

    def cleanup_schema(self):
        self.conn.rollback()
        self.conn.autocommit = True
        self.conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))

    def counts(self, data, question):
        return [o['count'] for chart in data['charts'] if chart['id'] == question for o in chart['options']]

    def test_counts_and_cross_filters(self):
        data = db.resultados_questionario(1, {})
        self.assertEqual((data['total'], data['matching']), (3, 3))
        self.assertEqual(self.counts(data, 1), [2, 1, 0])
        data = db.resultados_questionario(1, {'1': [1]})
        self.assertEqual(data['matching'], 2)
        self.assertEqual(self.counts(data, 2), [1, 1, 0])
        self.assertEqual(self.counts(data, 1), [2, 0, 0])
        self.assertEqual(data['charts'][0]['base'], 2)
        self.assertEqual(data['charts'][0]['options'][0]['count'] / data['charts'][0]['base'], 1)
        data = db.resultados_questionario(1, {'1': [1], '2': [5]})
        self.assertEqual(data['matching'], 1)
        self.assertEqual(self.counts(data, 1), [1, 0, 0])
        self.assertEqual(self.counts(data, 2), [0, 1, 0])
        self.assertEqual(db.resultados_questionario(1, {'1': [1, 2]})['matching'], 3)
        empty = db.resultados_questionario(1, {'1': [3]})
        self.assertEqual(empty['matching'], 0)
        self.assertTrue(all(chart['base'] == 0 for chart in empty['charts']))
        self.assertEqual(db.resultados_questionario(1, {})['matching'], 3)

    def test_invalid_filters_and_quiz_isolation(self):
        for filters in [{'1': [7]}, {'3': [7]}, {'1': [True]}, {'1': ['1']}, {'01': [1]}, {'x': []}]:
            with self.assertRaises(ValueError):
                db.resultados_questionario(1, filters)
        self.assertIsNone(db.resultados_questionario(999, {}))
        self.assertEqual(db.resultados_questionario(2, {})['total'], 1)
        self.conn.autocommit = True
        self.conn.execute('DELETE FROM respostas WHERE id_envio = 4')
        self.conn.execute('DELETE FROM envios WHERE id_envio = 4')
        self.conn.autocommit = False
        data = db.resultados_questionario(2, {})
        self.assertEqual((data['total'], data['matching']), (0, 0))
        self.assertEqual(self.counts(data, 3), [0])

    def test_profile_chart_and_bidirectional_filters(self):
        self.conn.autocommit = True
        self.conn.execute("UPDATE questionarios SET algoritmo = 'perfil_v1' WHERE id_questionario = 1")
        self.conn.execute('''UPDATE envios SET resultado = jsonb_build_object('category',
            CASE id_envio WHEN 1 THEN 'tecnologico' ELSE 'misto' END) WHERE id_envio IN (1,2)''')
        self.conn.autocommit = False
        data = db.resultados_questionario(1, {})
        chart = data['charts'][0]
        self.assertEqual(chart['id'], 'profiles')
        counts = {o['id']: o['count'] for o in chart['options']}
        self.assertEqual((counts['tecnologico'], counts['misto'], counts['sem_classificacao']), (1,1,1))
        data = db.resultados_questionario(1, {}, ['tecnologico'])
        self.assertEqual(data['matching'], 1)
        self.assertEqual(self.counts(data, 2), [1,0,0])
        data = db.resultados_questionario(1, {'2': [5]})
        counts = {o['id']: o['count'] for o in data['charts'][0]['options']}
        self.assertEqual((counts['tecnologico'], counts['misto'], counts['sem_classificacao']), (0,1,1))
        self.assertEqual(db.resultados_questionario(1, {'2':[5]}, ['tecnologico'])['matching'], 0)
        self.assertEqual(db.resultados_questionario(1, {}, ['misto','sem_classificacao'])['matching'], 2)
        for values in [['unknown'], 'tecnologico', [True]]:
            with self.assertRaises(ValueError):
                db.resultados_questionario(1, {}, values)
        self.assertEqual(len(db.resultados_questionario(2, {})['charts']), 1)
