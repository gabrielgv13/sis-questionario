"""Validate declarative scoring files against their questionnaire. Never executes code."""
import re

from .perfis import REGRAS, VERSAO, VERSAO_ANTERIOR, classificar
from .questionario_json import carregar_json


def texto(value, limite):
    if not isinstance(value, str) or not value.strip() or len(value) > limite or '\x00' in value:
        return False
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        return False
    return True


def validar(regras, questionario):
    if not isinstance(regras, dict) or set(regras) != {'version', 'profiles', 'questions'}:
        raise ValueError('Algoritmo: informe apenas version, profiles e questions.')
    if regras.get('version') == VERSAO_ANTERIOR:
        regras = {**regras, 'version': VERSAO}
    if not texto(regras['version'], 80) or regras['version'] != questionario['algoritmo']:
        raise ValueError('A version do algoritmo deve corresponder ao campo algoritmo do questionário.')
    profiles = regras['profiles']
    if (not isinstance(profiles, dict) or not 1 <= len(profiles) <= 32 or
            any(not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,79}', key)
                or key in ('misto', 'sem_classificacao') or not texto(label, 300)
                for key, label in profiles.items())):
        raise ValueError('Algoritmo: informe de 1 a 32 perfis com identificadores e nomes válidos; misto e sem_classificacao são reservados.')
    expected = {q['enunciado']: set(q['opcoes']) for q in questionario['perguntas']}
    questions = regras['questions']
    if not isinstance(questions, list) or len(questions) != len(expected):
        raise ValueError('O algoritmo deve conter exatamente as perguntas do questionário.')
    seen = set()
    for question in questions:
        if not isinstance(question, dict) or set(question) != {'title', 'options'}:
            raise ValueError('Algoritmo: cada pergunta deve conter title e options.')
        title, options = question['title'], question['options']
        if not isinstance(title, str) or title not in expected or title in seen:
            raise ValueError('Algoritmo: pergunta desconhecida ou repetida.')
        seen.add(title)
        if not isinstance(options, dict) or set(options) != expected[title]:
            raise ValueError(f'Algoritmo: alternativas incompatíveis na pergunta {title}.')
        for weights in options.values():
            if not isinstance(weights, dict) or set(weights) != {'add', 'subtract'}:
                raise ValueError('Cada alternativa deve conter add e subtract.')
            for kind, minimum, maximum in [('add', 0, 1000000), ('subtract', -1000000, 0)]:
                values = weights[kind]
                if (not isinstance(values, dict) or set(values) != set(profiles) or
                        any(type(n) is not int or not minimum <= n <= maximum for n in values.values())):
                    raise ValueError(f'Algoritmo: {kind} deve conter todos os perfis com inteiros entre {minimum} e {maximum}.')
    # Exercise calculation and tie handling with two complete answer sets.
    for last in (False, True):
        answers = {q['title']: list(q['options'])[-1 if last else 0] for q in questions}
        classificar(answers, regras)
    return regras


def ler_arquivo(conteudo, questionario):
    return validar(carregar_json(conteudo), questionario)


def regras_importacao(questionario, regras, *, legado=False):
    if questionario['algoritmo'] is None:
        if regras is not None:
            raise ValueError('O questionário não declara um algoritmo. Remova o arquivo de algoritmo.')
        return None
    if regras is None:
        if legado and questionario['algoritmo'] == VERSAO:
            regras = REGRAS
        else:
            raise ValueError('Selecione o arquivo JSON do algoritmo ' + questionario['algoritmo'] + '.')
    return validar(regras, questionario)


def regras_salvas(questionario):
    regras = questionario.get('regras_algoritmo')
    if regras is None and questionario.get('algoritmo') == VERSAO:
        return REGRAS  # Compatibility with questionnaires created before rules were stored.
    if questionario.get('algoritmo') and regras is None:
        raise ValueError('Arquivo de algoritmo ausente para este questionário.')
    return regras


def categorias(questionario):
    regras = regras_salvas(questionario)
    return {**(regras['profiles'] if regras else {}),
            'misto': 'Perfil misto', 'sem_classificacao': 'Sem classificação'}
