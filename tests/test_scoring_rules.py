import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from http_helpers import session_transaction
from sis_questionario.scoring_rules import parse_scoring_rules, resolve_import_rules, validate_scoring_rules
from sis_questionario.app import create_app
from sis_questionario.async_database import AsyncDatabase
from sis_questionario.profile_scoring import score_answers
from sis_questionario.questionnaire_import import MAX_BYTES, validate_questionnaire


def example_questionnaire_and_rules():
    quiz = json.loads(Path('tests/fixtures/questionnaire.template.json').read_text(encoding='utf-8'))
    rules = json.loads(Path('tests/fixtures/scoring_rules.template.json').read_text(encoding='utf-8'))
    quiz.update(algoritmo=rules['version'], exibir_resultado=True, ativo=True)
    return quiz, rules


class AlgorithmValidationTest(unittest.TestCase):
    def test_templates_and_custom_scoring(self):
        quiz, rules = example_questionnaire_and_rules()
        validate_questionnaire(quiz)
        self.assertEqual(validate_scoring_rules(rules, quiz), rules)
        answers = {q['title']: next(iter(q['options'])) for q in rules['questions']}
        result = score_answers(answers, rules)
        self.assertEqual(result['category'], 'perfil_a')
        self.assertEqual(result['scores'], {'perfil_a': 40, 'perfil_b': -10})
        self.assertEqual(result['version'], quiz['algoritmo'])

    def test_embedded_profile_still_requires_explicit_import_file(self):
        quiz = json.loads(Path('tests/fixtures/profile_questionnaire.json').read_text(encoding='utf-8'))
        with self.assertRaisesRegex(ValueError, 'Selecione'):
            resolve_import_rules(quiz, None)
        rules = Path('src/sis_questionario/profile_scoring_v1.json').read_bytes()
        self.assertEqual(parse_scoring_rules(rules, quiz)['version'], 'perfil_v1')

    def test_invalid_version_profiles_questions_options_and_numbers(self):
        quiz, original = example_questionnaire_and_rules()
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
                validate_scoring_rules(rules, quiz)

    def test_json_limits_duplicate_keys_and_unexpected_file(self):
        quiz, rules = example_questionnaire_and_rules()
        for raw in [b'{"version":"a","version":"b"}', b' ' * (MAX_BYTES + 1), b'{', b'\xff']:
            with self.assertRaises(ValueError):
                parse_scoring_rules(raw, quiz)
        quiz['algoritmo'] = None
        with self.assertRaises(ValueError):
            resolve_import_rules(quiz, rules)


class AlgorithmImportHttpTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(), base_url='https://testserver')
        self.addCleanup(self.client.close)
        self.client.cookies.set('id_dispositivo', 'a867914f-3056-493e-90a2-c53e9b9cb157')
        with session_transaction(self.client) as session:
            session.update(admin_authenticated=True, admin_csrf='token')
        self.quiz, self.rules = example_questionnaire_and_rules()

    def upload(self, rules=None):
        files = {'file': ('questionario.json', json.dumps(self.quiz).encode(), 'application/json')}
        if rules is not None:
            files['algorithm'] = ('perfil.json', rules, 'application/json')
        return self.client.post('/admin/api/questionnaires/import',
                                headers={'X-CSRF-Token': 'token'}, files=files)

    def test_missing_file_and_invalid_rules_never_reach_database(self):
        with patch.object(AsyncDatabase, 'import_questionnaire') as save:
            for rules in [None, b'{}', b'bad', b' ' * (MAX_BYTES + 1)]:
                response = self.upload(rules)
                self.assertEqual(response.status_code, 400)
                self.assertIn('error', response.json())
            save.assert_not_awaited()

    def test_valid_files_are_saved_together_and_can_be_exported(self):
        with patch.object(AsyncDatabase, 'import_questionnaire', return_value=7) as save:
            response = self.upload(json.dumps(self.rules).encode())
            self.assertEqual(response.status_code, 201)
            save.assert_awaited_once_with(self.quiz, self.rules)
        with patch.object(AsyncDatabase, 'export_scoring_rules', return_value=self.rules):
            response = self.client.get('/admin/api/questionnaires/7/algorithm')
        self.assertEqual(response.json(), self.rules)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertIn('attachment', response.headers['Content-Disposition'])

    def test_profile_v1_cannot_silently_use_server_file(self):
        self.quiz = json.loads(Path('tests/fixtures/profile_questionnaire.json').read_text(encoding='utf-8'))
        with patch.object(AsyncDatabase, 'import_questionnaire') as save:
            response = self.upload()
            self.assertEqual(response.status_code, 400)
            self.assertIn('perfil_v1', response.json()['error'])
            save.assert_not_awaited()
