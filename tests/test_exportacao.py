from fastapi.testclient import TestClient
from http_helpers import session_transaction
import copy
import csv
import io
import json
import unittest
from unittest.mock import patch

from sis_questionario import exportacao as exports
from sis_questionario.app import create_app
from sis_questionario.bd_async import AsyncDatabase


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.result = dict(title='Pesquisa de afinidades', total=10, matching=5, charts=[
            dict(id=1, title='Qual opção?', base=5, options=[
                dict(id=1, label='Ação', count=1, selected=False),
                dict(id=2, label='Ciência', count=4, selected=True)]),
            dict(id='profiles', title='Perfis', base=5, options=[
                dict(id='misto', label='Perfil misto', count=5, selected=False)])])
        self.payload = dict(quiz_id=1, format='json', mode='filtered', charts='all', filters={'1': [2]}, profiles=[])
        query = patch.object(exports.db, 'resultados_questionario', side_effect=lambda *args: copy.deepcopy(self.result))
        self.query = query.start()
        self.addCleanup(query.stop)

    def test_subset_keeps_all_filters_and_colors_and_order(self):
        self.payload.update(charts=['profiles'], orders={'1': 'asc'})
        data = exports.preparar(self.payload)
        self.query.assert_called_once_with(1, {'1': [2]}, [])
        self.assertEqual(len(data['charts']), 1)
        self.assertEqual(data['filters'][0]['options'], ['Ciência'])
        self.payload['charts'] = 'all'
        data = exports.preparar(self.payload)
        self.assertEqual([o['count'] for o in data['charts'][0]['options']], [1,4])
        self.assertEqual(data['charts'][0]['options'][1]['color'], exports.PALETA[1])
        self.payload['orders'] = {}
        self.assertEqual(exports.preparar(self.payload)['charts'][0]['options'][0]['count'], 4)

    def test_simple_removes_question_and_profile_filters(self):
        self.payload.update(mode='simple', profiles=['misto'])
        exports.preparar(self.payload)
        self.query.assert_called_once_with(1, {}, [])

    def test_invalid_parameters(self):
        for change in [dict(quiz_id=True), dict(format='html'), dict(mode='other'), dict(charts=[]),
                       dict(charts=['999']), dict(charts=[True]), dict(orders={'999': 'asc'}),
                       dict(orders={'1': 'bad'}), dict(filters=[])]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                exports.preparar({**self.payload, **change})
        self.query.side_effect = None
        self.query.return_value = None
        with self.assertRaises(ValueError):
            exports.preparar(self.payload)

    def test_csv_and_json_encoding_and_formula_protection(self):
        self.result['charts'][0]['options'][0]['label'] = '=DANGEROUS()'
        data = exports.preparar(self.payload)
        encoded = exports.gerar_csv(data)
        self.assertTrue(encoded.startswith(b'\xef\xbb\xbf'))
        rows = list(csv.DictReader(io.StringIO(encoded.decode('utf-8-sig')), delimiter=';'))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['alternativa'], 'Ciência')
        self.assertEqual(rows[1]['alternativa'], "'=DANGEROUS()")
        self.assertEqual(float(rows[0]['percentual']), 80)
        self.assertEqual(json.loads(exports.gerar_json(data))['charts'], data['charts'])

    def test_pdf_with_long_legends_and_empty_chart(self):
        self.result['charts'][0]['options'] *= 30
        self.result['charts'][1]['base'] = 0
        self.result['charts'][1]['options'][0]['count'] = 0
        data = exports.preparar(self.payload)
        pdf = exports.gerar_pdf(data)
        self.assertTrue(pdf.startswith(b'%PDF-'))
        self.assertTrue(pdf.rstrip().endswith(b'%%EOF'))
        self.assertGreater(pdf.count(b'/Type /Page\n'), 2)

    def test_endpoint_auth_csrf_and_attachment_formats(self):
        app = create_app(inicializar=False)
        client = TestClient(app, follow_redirects=False, base_url='https://testserver')
        with session_transaction(client) as session:
            session['admin_csrf'] = 'token'
        client.cookies.set('id_dispositivo', 'a867914f-3056-493e-90a2-c53e9b9cb157')
        self.assertEqual(client.post('/admin/api/export', json=self.payload).status_code, 401)
        with session_transaction(client) as session:
            session['admin_authenticated'] = True
        self.assertEqual(client.post('/admin/api/export', json=self.payload).status_code, 400)
        query = patch.object(AsyncDatabase, 'resultados_questionario', side_effect=lambda *args: copy.deepcopy(self.result))
        query.start()
        self.addCleanup(query.stop)
        for kind, mime in [('json','application/json'), ('csv','text/csv'), ('pdf','application/pdf')]:
            response = client.post('/admin/api/export', json={**self.payload, 'format': kind}, headers={'X-CSRF-Token': 'token'})
            self.assertEqual(response.status_code, 200)
            self.assertIn(mime, response.headers['content-type'])
            self.assertIn(f'questionario-1.{kind}', response.headers['Content-Disposition'])
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
