"""Pure validation and profile rules shared by sync CLI and async HTTP queries."""
from .perfis import VERSAO, classificar
from .algoritmo_json import regras_salvas
from .questionario_json import validar


def documento_questionario(codigo, titulo, perguntas, documento=None):
    return validar(documento if documento is not None else dict(
        schema_version=1, codigo=codigo, titulo=titulo, ativo=True,
        algoritmo=VERSAO if codigo == 'perfil' else None, exibir_resultado=codigo == 'perfil',
        perguntas=[dict(enunciado=p['pergunta'], opcoes=p['opcoes']) for p in perguntas]))


def resultado_envio(questionario, permitidas, respostas):
    pares = {(r['id_pergunta'], r['id_opcao']) for r in permitidas}
    perguntas = {p for p, _ in pares}
    if not perguntas or set(respostas) != perguntas or any((p, o) not in pares for p, o in respostas.items()):
        raise ValueError('Selecione uma opção válida para cada pergunta.')
    resultado = None
    if questionario['algoritmo']:
        selecionadas = {r['enunciado']: r['texto'] for r in permitidas
                        if respostas[r['id_pergunta']] == r['id_opcao']}
        resultado = classificar(selecionadas, regras_salvas(questionario))
    return resultado
