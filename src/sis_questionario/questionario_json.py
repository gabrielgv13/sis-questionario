"""Portable questionnaire format v1 (no database IDs or participant data)."""
import json
import re

from .perfis import VERSAO, VERSAO_ANTERIOR

MAX_BYTES = 1024 * 1024


def validar(documento):
    if isinstance(documento, dict) and documento.get('algoritmo') == VERSAO_ANTERIOR:
        documento = {**documento, 'algoritmo': VERSAO}
    campos = {'schema_version', 'codigo', 'titulo', 'ativo', 'algoritmo', 'exibir_resultado', 'perguntas'}
    if not isinstance(documento, dict) or set(documento) != campos:
        raise ValueError('Campos obrigatórios: ' + ', '.join(sorted(campos)) + '. Não são aceitos campos extras.')
    if type(documento['schema_version']) is not int or documento['schema_version'] != 1:
        raise ValueError('schema_version deve ser 1.')
    codigo = documento['codigo']
    if not isinstance(codigo, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', codigo):
        raise ValueError('codigo deve conter de 1 a 80 letras minúsculas, números, hífens ou sublinhados.')
    def texto(value, limite):
        if not isinstance(value, str) or not value.strip() or len(value) > limite or '\x00' in value:
            return False
        try:
            value.encode('utf-8')
        except UnicodeEncodeError:
            return False
        return True
    if not texto(documento['titulo'], 300):
        raise ValueError('titulo deve ter entre 1 e 300 caracteres.')
    if type(documento['ativo']) is not bool or type(documento['exibir_resultado']) is not bool:
        raise ValueError('ativo e exibir_resultado devem ser booleanos.')
    if documento['algoritmo'] is not None and not texto(documento['algoritmo'], 80):
        raise ValueError('algoritmo deve ser null ou um identificador de 1 a 80 caracteres.')
    if documento['exibir_resultado'] and documento['algoritmo'] is None:
        raise ValueError('Devolutiva exige um algoritmo configurado.')
    perguntas = documento['perguntas']
    if not isinstance(perguntas, list) or not 1 <= len(perguntas) <= 100:
        raise ValueError('Informe de 1 a 100 perguntas.')
    enunciados = set()
    for numero, pergunta in enumerate(perguntas, 1):
        if not isinstance(pergunta, dict) or set(pergunta) != {'enunciado', 'opcoes'}:
            raise ValueError(f'Pergunta {numero}: informe apenas enunciado e opcoes.')
        if not texto(pergunta['enunciado'], 2000) or pergunta['enunciado'].strip() in enunciados:
            raise ValueError(f'Pergunta {numero}: enunciado inválido ou repetido.')
        enunciados.add(pergunta['enunciado'].strip())
        opcoes = pergunta['opcoes']
        if (not isinstance(opcoes, list) or not 2 <= len(opcoes) <= 100 or
                any(not texto(opcao, 500) for opcao in opcoes) or
                len({opcao.strip() for opcao in opcoes}) != len(opcoes)):
            raise ValueError(f'Pergunta {numero}: informe de 2 a 100 alternativas distintas, com até 500 caracteres.')
    return documento


def ler_arquivo(conteudo):
    return validar(carregar_json(conteudo))


def carregar_json(conteudo):
    if len(conteudo) > MAX_BYTES:
        raise ValueError('O arquivo deve ter no máximo 1 MiB.')
    def objeto(pares):
        result = {}
        for chave, valor in pares:
            if chave in result:
                raise ValueError(f'Campo JSON repetido: {chave}.')
            result[chave] = valor
        return result
    try:
        documento = json.loads(conteudo.decode('utf-8-sig'), object_pairs_hook=objeto,
                               parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Número JSON inválido.')))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError('Arquivo inválido. Use JSON em UTF-8.') from error
    return documento
