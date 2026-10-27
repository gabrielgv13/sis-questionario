import json
import os
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from .config import carregar_configuracao


def conectar():
    carregar_configuracao()
    senha = os.environ.get('DB_PASSWORD')
    if not senha:
        raise RuntimeError('Configure DB_PASSWORD no .env ou nas variáveis de ambiente.')
    return psycopg.connect(
        host=os.environ.get('DB_HOST', 'localhost'),
        port=int(os.environ.get('DB_PORT', '5432')),
        dbname=os.environ.get('DB_NAME', 'mydatabase'),
        user=os.environ.get('DB_USER', 'client-app'),
        password=senha,
        row_factory=dict_row,
    )


def cadastrar_questionario(codigo, titulo, perguntas):
    """Cadastra uma vez por código. Reiniciar não altera perguntas já cadastradas."""
    if not codigo.strip() or not titulo.strip() or not perguntas:
        raise ValueError('Informe código, título e perguntas.')
    for pergunta in perguntas:
        opcoes = pergunta['opcoes']
        if not pergunta['pergunta'].strip() or len(opcoes) < 2:
            raise ValueError('Informe enunciado e pelo menos duas opções.')
        if any(not opcao.strip() for opcao in opcoes) or len(set(opcoes)) != len(opcoes):
            raise ValueError('As opções devem ser preenchidas e distintas.')
    with conectar() as conn:
        questionario = conn.execute(
            '''INSERT INTO questionarios (codigo, titulo) VALUES (%s, %s)
               ON CONFLICT (codigo) DO NOTHING RETURNING id_questionario''',
            (codigo, titulo),
        ).fetchone()
        if not questionario:
            return conn.execute(
                'SELECT id_questionario FROM questionarios WHERE codigo = %s', (codigo,),
            ).fetchone()['id_questionario']
        id_questionario = questionario['id_questionario']
        for ordem, pergunta in enumerate(perguntas, 1):
            id_pergunta = conn.execute(
                '''INSERT INTO perguntas (id_questionario, enunciado, ordem)
                   VALUES (%s, %s, %s) RETURNING id_pergunta''',
                (id_questionario, pergunta['pergunta'], ordem),
            ).fetchone()['id_pergunta']
            with conn.cursor() as cur:
                cur.executemany(
                    'INSERT INTO opcoes (id_pergunta, texto, ordem) VALUES (%s, %s, %s)',
                    [(id_pergunta, texto, i) for i, texto in enumerate(pergunta['opcoes'], 1)],
                )
        return id_questionario


def inicializar_banco():
    perguntas = json.loads(Path(__file__).with_name('perguntas.json').read_text(encoding='utf-8'))
    cadastrar_questionario('perfil', 'Questionário de perfil', perguntas)


def listar_questionarios():
    with conectar() as conn:
        return conn.execute('SELECT * FROM questionarios WHERE ativo ORDER BY titulo, id_questionario').fetchall()


def carregar_questionario(id_questionario):
    with conectar() as conn:
        questionario = conn.execute(
            'SELECT * FROM questionarios WHERE id_questionario = %s AND ativo', (id_questionario,),
        ).fetchone()
        if not questionario:
            return None
        perguntas = conn.execute(
            'SELECT * FROM perguntas WHERE id_questionario = %s ORDER BY ordem', (id_questionario,),
        ).fetchall()
        opcoes = conn.execute(
            '''SELECT o.* FROM opcoes o JOIN perguntas p ON p.id_pergunta = o.id_pergunta
               WHERE p.id_questionario = %s ORDER BY o.ordem''', (id_questionario,),
        ).fetchall()
        por_pergunta = {}
        for opcao in opcoes:
            por_pergunta.setdefault(opcao['id_pergunta'], []).append(opcao)
        for pergunta in perguntas:
            pergunta['opcoes'] = por_pergunta.get(pergunta['id_pergunta'], [])
        questionario['perguntas'] = perguntas
        return questionario


def registrar_aluno(nome, email):
    nome, email = nome.strip(), email.strip().lower()
    if not nome or not email:
        raise ValueError('Informe nome e e-mail.')
    with conectar() as conn:
        aluno = conn.execute(
            '''INSERT INTO alunos (nome, email) VALUES (%s, %s)
               ON CONFLICT (email) DO NOTHING RETURNING id_aluno''',
            (nome, email),
        ).fetchone()
        if aluno:
            return aluno['id_aluno']
        return conn.execute('SELECT id_aluno FROM alunos WHERE email = %s', (email,)).fetchone()['id_aluno']


class EnvioDuplicado(ValueError):
    pass


def dispositivo_ja_respondeu(id_dispositivo, id_questionario):
    with conectar() as conn:
        return conn.execute(
            'SELECT 1 FROM envios WHERE id_dispositivo = %s AND id_questionario = %s',
            (id_dispositivo, id_questionario),
        ).fetchone() is not None


def registrar_envio(id_aluno, id_questionario, respostas, id_dispositivo):
    id_dispositivo = UUID(str(id_dispositivo))
    with conectar() as conn:
        questionario = conn.execute(
            'SELECT id_questionario FROM questionarios WHERE id_questionario = %s AND ativo',
            (id_questionario,),
        ).fetchone()
        if not questionario:
            raise ValueError('Questionário indisponível. Selecione novamente na página inicial.')
        permitidas = conn.execute(
            '''SELECT p.id_pergunta, o.id_opcao FROM perguntas p
               JOIN opcoes o ON o.id_pergunta = p.id_pergunta WHERE p.id_questionario = %s''',
            (id_questionario,),
        ).fetchall()
        pares = {(r['id_pergunta'], r['id_opcao']) for r in permitidas}
        perguntas = {p for p, _ in pares}
        if not perguntas or set(respostas) != perguntas or any((p, o) not in pares for p, o in respostas.items()):
            raise ValueError('Selecione uma opção válida para cada pergunta.')
        envio = conn.execute(
            '''INSERT INTO envios (id_aluno, id_questionario, id_dispositivo)
               VALUES (%s, %s, %s)
               ON CONFLICT (id_dispositivo, id_questionario) DO NOTHING RETURNING id_envio''',
            (id_aluno, id_questionario, id_dispositivo),
        ).fetchone()
        if not envio:
            raise EnvioDuplicado('Este navegador já respondeu a este questionário.')
        id_envio = envio['id_envio']
        with conn.cursor() as cur:
            cur.executemany(
                'INSERT INTO respostas (id_envio, id_pergunta, id_opcao) VALUES (%s, %s, %s)',
                [(id_envio, p, o) for p, o in respostas.items()],
            )
        return id_envio
