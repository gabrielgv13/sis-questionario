import copy
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from sis_questionario.questionario_json import MAX_BYTES, ler_arquivo, validar
from sis_questionario.app import create_app
from sis_questionario import bd_exec as db


def exemplo():
    return dict(schema_version=1, codigo='teste', titulo='Questionário de teste', ativo=True,
                algoritmo=None, exibir_resultado=False,
                perguntas=[dict(enunciado='Escolha uma opção', opcoes=['Ação', 'Comédia'])])


class QuestionnaireJsonTest(unittest.TestCase):
    def test_valid_roundtrip_bom_and_profile_example(self):
        doc = exemplo()
        self.assertEqual(ler_arquivo(json.dumps(doc).encode('utf-8-sig')), doc)
        profile = Path(__file__).resolve().parents[1] / 'docs/questionario_perfil.json'
        self.assertEqual(len(ler_arquivo(profile.read_bytes())['perguntas']), 11)

    def test_invalid_documents(self):
        for changes in [dict(schema_version=True), dict(schema_version=2), dict(codigo='../x'),
                        dict(titulo=' '), dict(titulo='Texto\x00'), dict(titulo='\ud800'), dict(ativo=1), dict(algoritmo='unknown'),
                        dict(exibir_resultado=True), dict(perguntas=[]), dict(extra='field'),
                        dict(algoritmo='perfil_v1')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validar({**exemplo(), **changes})
        for question in [dict(enunciado='Q',opcoes=['A',' A ']), dict(enunciado='Q',opcoes=['A']),
                         dict(enunciado='Q',opcoes=['A',None]), dict(enunciado='',opcoes=['A','B'])]:
            with self.subTest(question=question), self.assertRaises(ValueError):
                validar({**exemplo(), 'perguntas': [question]})

    def test_invalid_encoding_duplicate_keys_and_size(self):
        for raw in [b'not json', b'\xff', b'{"a":1,"a":2}', b'{"a":NaN}', b' '*(MAX_BYTES+1)]:
            with self.assertRaises(ValueError):
                ler_arquivo(raw)

    def test_authenticated_endpoints_and_error_feedback(self):
        app = create_app(inicializar=False)
        app.testing = True
        client = app.test_client()
        client.set_cookie('id_dispositivo', 'a867914f-3056-493e-90a2-c53e9b9cb157')
        self.assertEqual(client.get('/admin/api/questionnaires/1/export').status_code, 401)
        with client.session_transaction() as session:
            session.update(admin_authenticated=True, admin_csrf='token')
        raw = json.dumps(exemplo()).encode()
        def upload(headers=None, content=raw):
            return client.post('/admin/api/questionnaires/import', headers=headers,
                               data={'file': (io.BytesIO(content), 'questionario.json')})
        self.assertEqual(upload().status_code, 400)
        headers = {'X-CSRF-Token': 'token'}
        self.assertEqual(upload(headers, b'bad').status_code, 400)
        with patch.object(db, 'importar_questionario', return_value=7) as save:
            self.assertEqual(upload(headers).status_code, 201)
            save.assert_called_once_with(exemplo())
        with patch.object(db, 'importar_questionario', side_effect=db.QuestionarioExistente('Já existe')):
            self.assertEqual(upload(headers).status_code, 409)
        with patch.object(db, 'exportar_questionario', return_value=exemplo()):
            exported = client.get('/admin/api/questionnaires/1/export')
            self.assertEqual(exported.json, exemplo())
            self.assertIn('attachment', exported.headers['Content-Disposition'])
            self.assertEqual(exported.headers['Cache-Control'], 'no-store')
        with patch.object(db, 'exportar_questionario', return_value=None):
            self.assertEqual(client.get('/admin/api/questionnaires/999/export').status_code, 404)
