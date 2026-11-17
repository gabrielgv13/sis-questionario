"""Validate declarative scoring files against their questionnaire. Never executes code."""
import re

from .profile_scoring import DEFAULT_SCORING_RULES, SCORING_VERSION, LEGACY_SCORING_VERSION, score_answers
from .questionnaire_import import is_valid_text, load_json


def validate_scoring_rules(rules, questionnaire):
    if not isinstance(rules, dict) or set(rules) != {'version', 'profiles', 'questions'}:
        raise ValueError('Algoritmo: informe apenas version, profiles e questions.')
    if rules.get('version') == LEGACY_SCORING_VERSION:
        rules = {**rules, 'version': SCORING_VERSION}
    if not is_valid_text(rules['version'], 80) or rules['version'] != questionnaire['algoritmo']:
        raise ValueError('A version do algoritmo deve corresponder ao campo algoritmo do questionário.')
    profiles = rules['profiles']
    if (not isinstance(profiles, dict) or not 1 <= len(profiles) <= 32 or
            any(not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,79}', key)
                or key in ('misto', 'sem_classificacao') or not is_valid_text(label, 300)
                for key, label in profiles.items())):
        raise ValueError('Algoritmo: informe de 1 a 32 perfis com identificadores e nomes válidos; misto e sem_classificacao são reservados.')
    expected_options = {
        question['enunciado']: set(question['opcoes'])
        for question in questionnaire['perguntas']
    }
    questions = rules['questions']
    if not isinstance(questions, list) or len(questions) != len(expected_options):
        raise ValueError('O algoritmo deve conter exatamente as perguntas do questionário.')
    seen_titles = set()
    for question in questions:
        if not isinstance(question, dict) or set(question) != {'title', 'options'}:
            raise ValueError('Algoritmo: cada pergunta deve conter title e options.')
        title, options = question['title'], question['options']
        if not isinstance(title, str) or title not in expected_options or title in seen_titles:
            raise ValueError('Algoritmo: pergunta desconhecida ou repetida.')
        seen_titles.add(title)
        if not isinstance(options, dict) or set(options) != expected_options[title]:
            raise ValueError(f'Algoritmo: alternativas incompatíveis na pergunta {title}.')
        for weights in options.values():
            if not isinstance(weights, dict) or set(weights) != {'add', 'subtract'}:
                raise ValueError('Cada alternativa deve conter add e subtract.')
            for kind, minimum, maximum in [('add', 0, 1000000), ('subtract', -1000000, 0)]:
                values = weights[kind]
                if (not isinstance(values, dict) or set(values) != set(profiles) or
                        any(type(n) is not int or not minimum <= n <= maximum for n in values.values())):
                    raise ValueError(f'Algoritmo: {kind} deve conter todos os perfis com inteiros entre {minimum} e {maximum}.')
    for option_index in (0, -1):
        sample_answers = {
            question['title']: list(question['options'])[option_index]
            for question in questions
        }
        score_answers(sample_answers, rules)
    return rules


def parse_scoring_rules(content, questionnaire):
    return validate_scoring_rules(load_json(content), questionnaire)


def resolve_import_rules(questionnaire, rules, *, allow_builtin_rules=False):
    if questionnaire['algoritmo'] is None:
        if rules is not None:
            raise ValueError('O questionário não declara um algoritmo. Remova o arquivo de algoritmo.')
        return None
    if rules is None:
        if allow_builtin_rules and questionnaire['algoritmo'] == SCORING_VERSION:
            rules = DEFAULT_SCORING_RULES
        else:
            raise ValueError('Selecione o arquivo JSON do algoritmo ' + questionnaire['algoritmo'] + '.')
    return validate_scoring_rules(rules, questionnaire)


def get_stored_rules(questionnaire):
    rules = questionnaire.get('regras_algoritmo')
    if rules is None and questionnaire.get('algoritmo') == SCORING_VERSION:
        return DEFAULT_SCORING_RULES  # Compatibility with questionnaires created before rules were stored.
    if questionnaire.get('algoritmo') and rules is None:
        raise ValueError('Arquivo de algoritmo ausente para este questionário.')
    return rules


def get_category_labels(questionnaire):
    rules = get_stored_rules(questionnaire)
    return {**(rules['profiles'] if rules else {}),
            'misto': 'Perfil misto', 'sem_classificacao': 'Sem classificação'}
