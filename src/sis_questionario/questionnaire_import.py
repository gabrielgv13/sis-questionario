"""Portable questionnaire format v1 (no database IDs or participant data)."""
import json
import re

from .profile_scoring import SCORING_VERSION, LEGACY_SCORING_VERSION

MAX_BYTES = 1024 * 1024


def build_questionnaire_document(code, title, questions, document=None):
    if document is None:
        uses_profile_scoring = code == 'perfil'
        document = {
            'schema_version': 1,
            'codigo': code,
            'titulo': title,
            'ativo': True,
            'algoritmo': SCORING_VERSION if uses_profile_scoring else None,
            'exibir_resultado': uses_profile_scoring,
            'perguntas': [
                {'enunciado': question['pergunta'], 'opcoes': question['opcoes']}
                for question in questions
            ],
        }
    return validate_questionnaire(document)


def is_valid_text(value, max_length):
    if not isinstance(value, str) or not value.strip() or len(value) > max_length or '\x00' in value:
        return False
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        return False
    return True


def validate_questionnaire(document):
    if isinstance(document, dict) and document.get('algoritmo') == LEGACY_SCORING_VERSION:
        document = {**document, 'algoritmo': SCORING_VERSION}
    required_fields = {'schema_version', 'codigo', 'titulo', 'ativo', 'algoritmo', 'exibir_resultado', 'perguntas'}
    if not isinstance(document, dict) or set(document) != required_fields:
        raise ValueError('Campos obrigatórios: ' + ', '.join(sorted(required_fields)) + '. Não são aceitos campos extras.')
    if type(document['schema_version']) is not int or document['schema_version'] != 1:
        raise ValueError('schema_version deve ser 1.')
    code = document['codigo']
    if not isinstance(code, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', code):
        raise ValueError('codigo deve conter de 1 a 80 letras minúsculas, números, hífens ou sublinhados.')
    if not is_valid_text(document['titulo'], 300):
        raise ValueError('titulo deve ter entre 1 e 300 caracteres.')
    if type(document['ativo']) is not bool or type(document['exibir_resultado']) is not bool:
        raise ValueError('ativo e exibir_resultado devem ser booleanos.')
    if document['algoritmo'] is not None and not is_valid_text(document['algoritmo'], 80):
        raise ValueError('algoritmo deve ser null ou um identificador de 1 a 80 caracteres.')
    if document['exibir_resultado'] and document['algoritmo'] is None:
        raise ValueError('Devolutiva exige um algoritmo configurado.')
    questions = document['perguntas']
    if not isinstance(questions, list) or not 1 <= len(questions) <= 100:
        raise ValueError('Informe de 1 a 100 perguntas.')
    seen_prompts = set()
    for number, question in enumerate(questions, 1):
        if not isinstance(question, dict) or set(question) != {'enunciado', 'opcoes'}:
            raise ValueError(f'Pergunta {number}: informe apenas enunciado e opcoes.')
        if not is_valid_text(question['enunciado'], 2000) or question['enunciado'].strip() in seen_prompts:
            raise ValueError(f'Pergunta {number}: enunciado inválido ou repetido.')
        seen_prompts.add(question['enunciado'].strip())
        options = question['opcoes']
        if (not isinstance(options, list) or not 2 <= len(options) <= 100 or
                any(not is_valid_text(option, 500) for option in options) or
                len({option.strip() for option in options}) != len(options)):
            raise ValueError(f'Pergunta {number}: informe de 2 a 100 alternativas distintas, com até 500 caracteres.')
    return document


def parse_questionnaire(content):
    return validate_questionnaire(load_json(content))


def load_json(content):
    if len(content) > MAX_BYTES:
        raise ValueError('O arquivo deve ter no máximo 1 MiB.')
    def build_unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Campo JSON repetido: {key}.')
            result[key] = value
        return result
    try:
        document = json.loads(content.decode('utf-8-sig'), object_pairs_hook=build_unique_object,
                               parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Número JSON inválido.')))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError('Arquivo inválido. Use JSON em UTF-8.') from error
    return document
