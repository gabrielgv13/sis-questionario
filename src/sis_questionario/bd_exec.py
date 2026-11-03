import json
import os
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import carregar_configuracao
from .perfis import CATEGORIAS, VERSAO, classificar


def conectar():
    carregar_configuracao()
    senha = os.environ.get('DB_PASSWORD', 'postgres')
    return psycopg.connect(
        host=os.environ.get('DB_HOST', 'localhost'),
        port=int(os.environ.get('DB_PORT', '5432')),
        dbname=os.environ.get('DB_NAME', 'mydatabase'),
        user=os.environ.get('DB_USER', 'postgres'),
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
            '''INSERT INTO questionarios (codigo, titulo, algoritmo, exibir_resultado)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (codigo) DO NOTHING RETURNING id_questionario''',
            (codigo, titulo, VERSAO if codigo == 'perfil' else None, codigo == 'perfil'),
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


def listar_questionarios_admin():
    with conectar() as conn:
        return conn.execute('SELECT * FROM questionarios ORDER BY titulo, id_questionario').fetchall()


def resultados_questionario(id_questionario, filtros, perfis=None):
    """Apply every selected filter to the same submissions in every chart."""
    with conectar() as conn:
        # All charts and totals must describe the same database snapshot.
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        quiz = conn.execute('SELECT titulo, algoritmo, exibir_resultado FROM questionarios WHERE id_questionario = %s',
                            (id_questionario,)).fetchone()
        if not quiz:
            return None
        perfis = [] if perfis is None else perfis
        if (not isinstance(perfis, list) or any(not isinstance(p, str) or p not in CATEGORIAS for p in perfis)
                or (perfis and not quiz['algoritmo'])):
            raise ValueError('Filtro de perfil inválido.')
        perguntas = conn.execute('SELECT id_pergunta, enunciado FROM perguntas '
                                 'WHERE id_questionario = %s ORDER BY ordem', (id_questionario,)).fetchall()
        opcoes = conn.execute('''SELECT o.id_opcao, o.id_pergunta, o.texto FROM opcoes o
            JOIN perguntas p USING (id_pergunta) WHERE p.id_questionario = %s
            ORDER BY p.ordem, o.ordem''', (id_questionario,)).fetchall()
        validas = {}
        for opcao in opcoes:
            validas.setdefault(opcao['id_pergunta'], set()).add(opcao['id_opcao'])
        selecionadas = {}
        for chave, valores in filtros.items():
            if not isinstance(chave, str) or not chave.isdecimal() or not isinstance(valores, list):
                raise ValueError('Filtros inválidos.')
            pergunta = int(chave)
            if (str(pergunta) != chave or pergunta not in validas or
                    any(type(v) is not int or v not in validas[pergunta] for v in valores)):
                raise ValueError('Opção não pertence à pergunta ou ao questionário.')
            if valores:
                selecionadas[pergunta] = list(set(valores))

        def condicao():
            partes = [sql.SQL('e.id_questionario = %s')]
            params = [id_questionario]
            if perfis:
                partes.append(sql.SQL("COALESCE(e.resultado->>'category', 'sem_classificacao') = ANY(%s)"))
                params.append(perfis)
            for pergunta, valores in selecionadas.items():
                partes.append(sql.SQL('''EXISTS (SELECT 1 FROM respostas f
                    WHERE f.id_envio = e.id_envio AND f.id_pergunta = %s
                    AND f.id_opcao = ANY(%s))'''))
                params.extend([pergunta, valores])
            return sql.SQL(' AND ').join(partes), params

        total = conn.execute('SELECT COUNT(*) AS n FROM envios WHERE id_questionario = %s',
                             (id_questionario,)).fetchone()['n']
        where, params = condicao()
        matching = conn.execute(sql.SQL('SELECT COUNT(*) AS n FROM envios e WHERE {}').format(where),
                                params).fetchone()['n']
        charts = []
        for pergunta in perguntas:
            pid = pergunta['id_pergunta']
            where, params = condicao()
            rows = conn.execute(sql.SQL('''SELECT r.id_opcao, COUNT(*) AS n FROM respostas r
                JOIN envios e USING (id_envio) WHERE r.id_pergunta = %s AND {}
                GROUP BY r.id_opcao''').format(where), [pid, *params]).fetchall()
            counts = {r['id_opcao']: r['n'] for r in rows}
            options = [dict(id=o['id_opcao'], label=o['texto'], count=counts.get(o['id_opcao'], 0),
                            selected=o['id_opcao'] in selecionadas.get(pid, []))
                       for o in opcoes if o['id_pergunta'] == pid]
            charts.append(dict(id=pid, title=pergunta['enunciado'], options=options,
                               base=sum(o['count'] for o in options)))
        if quiz['algoritmo']:
            rows = conn.execute(sql.SQL("""SELECT COALESCE(e.resultado->>'category',
                'sem_classificacao') AS categoria, COUNT(*) AS n FROM envios e
                WHERE {} GROUP BY categoria""").format(where), params).fetchall()
            counts = {row['categoria']: row['n'] for row in rows}
            charts.insert(0, dict(id='profiles', title='Perfis dos participantes', base=matching,
                options=[dict(id=key, label=label, count=counts.get(key, 0), selected=key in perfis)
                         for key, label in CATEGORIAS.items()]))
        return dict(title=quiz['titulo'], total=total, matching=matching, charts=charts,
                    algorithm=quiz['algoritmo'], show_result=quiz['exibir_resultado'])


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
            'SELECT id_questionario, algoritmo FROM questionarios WHERE id_questionario = %s AND ativo',
            (id_questionario,),
        ).fetchone()
        if not questionario:
            raise ValueError('Questionário indisponível. Selecione novamente na página inicial.')
        permitidas = conn.execute(
            '''SELECT p.id_pergunta, p.enunciado, o.id_opcao, o.texto FROM perguntas p
               JOIN opcoes o ON o.id_pergunta = p.id_pergunta WHERE p.id_questionario = %s''',
            (id_questionario,),
        ).fetchall()
        pares = {(r['id_pergunta'], r['id_opcao']) for r in permitidas}
        perguntas = {p for p, _ in pares}
        if not perguntas or set(respostas) != perguntas or any((p, o) not in pares for p, o in respostas.items()):
            raise ValueError('Selecione uma opção válida para cada pergunta.')
        resultado = None
        if questionario['algoritmo']:
            if questionario['algoritmo'] != VERSAO:
                raise ValueError('Algoritmo de classificação indisponível.')
            selecionadas = {r['enunciado']: r['texto'] for r in permitidas
                            if respostas[r['id_pergunta']] == r['id_opcao']}
            resultado = classificar(selecionadas)
        envio = conn.execute(
            '''INSERT INTO envios (id_aluno, id_questionario, id_dispositivo, resultado)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (id_dispositivo, id_questionario) DO NOTHING RETURNING id_envio''',
            (id_aluno, id_questionario, id_dispositivo, Jsonb(resultado) if resultado else None),
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


def carregar_resultado(id_envio, id_dispositivo):
    with conectar() as conn:
        row = conn.execute('''SELECT e.resultado FROM envios e
            JOIN questionarios q USING (id_questionario)
            WHERE e.id_envio = %s AND e.id_dispositivo = %s AND q.exibir_resultado''',
            (id_envio, id_dispositivo)).fetchone()
        return row['resultado'] if row else None


def configurar_devolutiva(id_questionario, habilitada):
    with conectar() as conn:
        row = conn.execute('''UPDATE questionarios SET exibir_resultado = %s
            WHERE id_questionario = %s AND algoritmo IS NOT NULL RETURNING id_questionario''',
            (habilitada, id_questionario)).fetchone()
        if not row:
            raise ValueError('Questionário sem algoritmo de classificação.')
