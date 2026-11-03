"""Versioned profile heuristic. Weights are keyed by question and option text."""
import json
from pathlib import Path

REGRAS = json.loads(Path(__file__).with_name('perfil_v1.json').read_text(encoding='utf-8'))
PERFIS = REGRAS['profiles']
CATEGORIAS = {**PERFIS, 'misto': 'Perfil misto', 'sem_classificacao': 'Sem classificação'}
VERSAO = REGRAS['version']
VERSAO_ANTERIOR = bytes.fromhex('70657266696c5f736573695f7631').decode('ascii')


def concluir(pontos, fortes):
    candidatos = [p for p in PERFIS if pontos[p] == max(pontos.values())]
    maior = max(fortes[p] for p in candidatos)
    vencedores = [p for p in candidatos if fortes[p] == maior]
    return dict(version=VERSAO, scores=pontos, strong=fortes, winners=vencedores,
                category=vencedores[0] if len(vencedores) == 1 else 'misto')


def classificar(respostas):
    """respostas maps question text to the selected option text, never DB IDs."""
    if set(respostas) != {q['title'] for q in REGRAS['questions']}:
        raise ValueError('As perguntas não correspondem à versão do classificador de perfil.')
    pontos = dict.fromkeys(PERFIS, 0)
    fortes = dict.fromkeys(PERFIS, 0)
    for pergunta in REGRAS['questions']:
        regra = pergunta['options'].get(respostas[pergunta['title']])
        if regra is None:
            raise ValueError('Alternativa sem regra de classificação.')
        for perfil in PERFIS:
            pontos[perfil] += regra['add'][perfil] + regra['subtract'][perfil]
            fortes[perfil] += regra['add'][perfil] == 20
    return concluir(pontos, fortes)
