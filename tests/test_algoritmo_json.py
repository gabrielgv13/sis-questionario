import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from http_helpers import session_transaction
from sis_questionario.algoritmo_json import ler_arquivo, regras_importacao, validar
from sis_questionario.app import create_app
from sis_questionario.bd_async import AsyncDatabase
from sis_questionario.perfis import classificar
from sis_questionario.questionario_json import MAX_BYTES, validar as validar_questionario


def exemplos():
    quiz = json.loads(Path('docs/questionario.template.json').read_text(encoding='utf-8'))
    rules = json.loads(Path('docs/perfil.template.json').read_text(encoding='utf-8'))
    quiz.update(algoritmo=rules['version'], exibir_resultado=True, ativo=True)
    return quiz, rules


class AlgorithmValidationTest(unittest.TestCase):
    def test_templates_and_custom_scoring(self):
        quiz, rules = exemplos()
        validar_questionario(quiz)
        self.assertEqual(validar(rules, quiz), rules)
        answers = {q['title']: next(iter(q['options'])) for q in rules['questions']}
        result = classificar(answers, rules)
        self.assertEqual(result['category'], 'perfil_a')
        self.assertEqual(result['scores'], {'perfil_a': 40, 'perfil_b': -10})
        self.assertEqual(result['version'], quiz['algoritmo'])

    def test_embedded_profile_still_requires_explicit_import_file(self):
        quiz = json.loads(Path('docs/questionario_perfil.json').read_text(encoding='utf-8'))
        with self.assertRaisesRegex(ValueError, 'Selecione'):
            regras_importacao(quiz, None)
        rules = Path('src/sis_questionario/perfil_v1.json').read_bytes()
        self.assertEqual(ler_arquivo(rules, quiz)['version'], 'perfil_v1')

    def test_invalid_version_profiles_questions_options_and_numbers(self):
        quiz, original = exemplos()
        bad = []
        rules = copy.deepcopy(original); rules['version'] = 'other'; bad.append(rules)
        rules = copy.deepcopy(original); rules['profiles'] = {}; bad.append(rules)
        rules = copy.deepcopy(original); rules['profiles']['misto'] = 'Reserved'; bad.append(rules)
        rules = copy.deepcopy(original); rules['questions'].pop(); bad.append(rules)
        rules = copy.deepcopy(original); rules['questions'][1] = rules['questions'][0]; bad.append(rules)
        rules = copy.deepcopy(original); rules['questions'][0]['options'].popitem(); bad.append(rules)
        rules = copy.deepcopy(original); rules['questions'][0]['title'] = []; bad.append(rules)
        for kind, value in [('add', True), ('add', 1.5), ('add', -1), ('add', 1000001), ('subtract', 1)]:
            rules = copy.deepcopy(original)
            first = next(iter(rules['questions'][0]['options'].values()))
            first[kind]['perfil_a'] = value
            bad.append(rules)
        rules = copy.deepcopy(original); next(iter(rules['questions'][0]['options'].values()))['add'].pop('perfil_b'); bad.append(rules)
        for rules in bad:
            with self.subTest(rules=rules), self.assertRaises(ValueError):
                validar(rules, quiz)

    def test_json_limits_duplicate_keys_and_unexpected_file(self):
        quiz, rules = exemplos()
        for raw in [b'{"version":"a","version":"b"}', b' ' * (MAX_BYTES + 1), b'{', b'\xff']:
            with self.assertRaises(ValueError):
                ler_arquivo(raw, quiz)
        quiz['algoritmo'] = None
        with self.assertRaises(ValueError):
            regras_importacao(quiz, rules)


class AlgorithmImportHttpTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(), base_url='https://testserver')
        self.addCleanup(self.client.close)
        self.client.cookies.set('id_dispositivo', 'a867914f-3056-493e-90a2-c53e9b9cb157')
        with session_transaction(self.client) as session:
            session.update(admin_authenticated=True, admin_csrf='token')
        self.quiz, self.rules = exemplos()

    def upload(self, rules=None):
        files = {'file': ('questionario.json', json.dumps(self.quiz).encode(), 'application/json')}
        if rules is not None:
            files['algorithm'] = ('perfil.json', rules, 'application/json')
        return self.client.post('/admin/api/questionnaires/import',
                                headers={'X-CSRF-Token': 'token'}, files=files)

    def test_missing_file_and_invalid_rules_never_reach_database(self):
        with patch.object(AsyncDatabase, 'importar_questionario') as save:
            for rules in [None, b'{}', b'bad', b' ' * (MAX_BYTES + 1)]:
                response = self.upload(rules)
                self.assertEqual(response.status_code, 400)
                self.assertIn('error', response.json())
            save.assert_not_awaited()

    def test_valid_files_are_saved_together_and_can_be_exported(self):
        with patch.object(AsyncDatabase, 'importar_questionario', return_value=7) as save:
            response = self.upload(json.dumps(self.rules).encode())
            self.assertEqual(response.status_code, 201)
            save.assert_awaited_once_with(self.quiz, self.rules)
        with patch.object(AsyncDatabase, 'exportar_algoritmo', return_value=self.rules):
            response = self.client.get('/admin/api/questionnaires/7/algorithm')
        self.assertEqual(response.json(), self.rules)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertIn('attachment', response.headers['Content-Disposition'])

    def test_profile_v1_cannot_silently_use_server_file(self):
        self.quiz = json.loads(Path('docs/questionario_perfil.json').read_text(encoding='utf-8'))
        with patch.object(AsyncDatabase, 'importar_questionario') as save:
            response = self.upload()
            self.assertEqual(response.status_code, 400)
            self.assertIn('perfil_v1', response.json()['error'])
            save.assert_not_awaited()
