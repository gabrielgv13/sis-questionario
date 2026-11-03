import json
import unittest
from pathlib import Path

from sis_questionario import perfis


class PerfilRulesTest(unittest.TestCase):
    def test_all_questions_and_120_options_have_rules(self):
        source = json.loads(Path(perfis.__file__).with_name('perguntas.json').read_text(encoding='utf-8'))
        self.assertEqual(len(perfis.REGRAS['questions']), 11)
        self.assertEqual(sum(len(q['options']) for q in perfis.REGRAS['questions']), 120)
        for question, rule in zip(source, perfis.REGRAS['questions'], strict=True):
            self.assertEqual(question['pergunta'], rule['title'])
            self.assertEqual(set(question['opcoes']), set(rule['options']))
            for weights in rule['options'].values():
                self.assertEqual(set(weights['add']), set(perfis.PERFIS))
                self.assertEqual(set(weights['subtract']), set(perfis.PERFIS))
                self.assertTrue(all(n >= 0 for n in weights['add'].values()))
                self.assertTrue(all(n <= 0 for n in weights['subtract'].values()))

    def test_manual_first_options_example(self):
        answers = {q['title']: next(iter(q['options'])) for q in perfis.REGRAS['questions']}
        result = perfis.classificar(answers)
        self.assertEqual(result['scores'], dict(politico=115, identitario=115, tecnologico=25, esportes=140, otaku=75))
        self.assertEqual(result['strong'], dict(politico=4, identitario=4, tecnologico=1, esportes=6, otaku=2))
        self.assertEqual(result['category'], 'esportes')

    def test_tiebreak_mixed_and_negative_scores(self):
        scores = dict.fromkeys(perfis.PERFIS, -20)
        scores.update(politico=-5, identitario=-5)
        strong = dict.fromkeys(perfis.PERFIS, 0)
        strong['politico'] = 2
        self.assertEqual(perfis.concluir(scores, strong)['category'], 'politico')
        strong['identitario'] = 2
        result = perfis.concluir(scores, strong)
        self.assertEqual(result['category'], 'misto')
        self.assertEqual(result['winners'], ['politico', 'identitario'])

    def test_education_food_and_cumulative_subtractions(self):
        rules = perfis.REGRAS['questions']
        education = rules[7]['options']['Educação']['add']
        self.assertEqual(education, dict(politico=20, identitario=20, tecnologico=10, esportes=20, otaku=0))
        for option, weights in rules[8]['options'].items():
            self.assertEqual(weights['add']['tecnologico'], 15 if option.startswith('Prato popular') else 5)
            self.assertTrue(all(weights['add'][p] == 5 for p in perfis.PERFIS if p != 'tecnologico'))
        kof = rules[10]['options']['The King Of Fighters']
        self.assertEqual(kof['add']['esportes'] + kof['subtract']['esportes'], 5)

    def test_missing_or_unknown_answers_rejected(self):
        with self.assertRaises(ValueError):
            perfis.classificar({})
        answers = {q['title']: next(iter(q['options'])) for q in perfis.REGRAS['questions']}
        answers[next(iter(answers))] = 'Unknown'
        with self.assertRaises(ValueError):
            perfis.classificar(answers)
