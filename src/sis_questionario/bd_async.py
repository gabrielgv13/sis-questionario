"""Async PostgreSQL repository. Each operation owns its transaction and connection."""
from uuid import UUID

from psycopg import sql
from psycopg.types.json import Jsonb

from .bd_exec import EnvioDuplicado, QuestionarioExistente
from .bd_rules import documento_questionario, resultado_envio
from .algoritmo_json import categorias, regras_importacao, regras_salvas
from .questionario_json import validar


class AsyncDatabase:
    EnvioDuplicado = EnvioDuplicado
    QuestionarioExistente = QuestionarioExistente

    def __init__(self, pool):
        self.pool = pool

    async def check_health(self):
        async with self.pool.connection() as conn:
            await conn.execute('SELECT 1 FROM questionarios LIMIT 1')

    async def cadastrar_questionario(self, codigo, titulo, perguntas, *, documento=None, estrito=False, regras=None):
        """Cadastra uma vez por código. Reiniciar não altera perguntas já cadastradas."""
        documento = documento_questionario(codigo, titulo, perguntas, documento)
        regras = regras_importacao(documento, regras, legado=not estrito)
        async with self.pool.connection() as conn:
            questionario = (await (await conn.execute(
                '''INSERT INTO questionarios (codigo, titulo, ativo, algoritmo, exibir_resultado, documento, regras_algoritmo)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (codigo) DO NOTHING RETURNING id_questionario''',
                (documento['codigo'], documento['titulo'], documento['ativo'], documento['algoritmo'],
                 documento['exibir_resultado'], Jsonb(documento), Jsonb(regras) if regras else None),
            )).fetchone())
            if not questionario:
                if estrito:
                    raise QuestionarioExistente('Já existe um questionário com esse código. Altere o campo codigo no arquivo para importar uma cópia.')
                return (await (await conn.execute(
                    'SELECT id_questionario FROM questionarios WHERE codigo = %s', (codigo,),
                )).fetchone())['id_questionario']
            id_questionario = questionario['id_questionario']
            for ordem, pergunta in enumerate(documento['perguntas'], 1):
                id_pergunta = (await (await conn.execute(
                    '''INSERT INTO perguntas (id_questionario, enunciado, ordem)
                       VALUES (%s, %s, %s) RETURNING id_pergunta''',
                    (id_questionario, pergunta['enunciado'], ordem),
                )).fetchone())['id_pergunta']
                async with conn.cursor() as cur:
                    (await cur.executemany(
                        'INSERT INTO opcoes (id_pergunta, texto, ordem) VALUES (%s, %s, %s)',
                        [(id_pergunta, texto, i) for i, texto in enumerate(pergunta['opcoes'], 1)],
                    ))
            return id_questionario

    async def importar_questionario(self, documento, regras=None):
        documento = validar(documento)
        return await self.cadastrar_questionario(documento['codigo'], documento['titulo'], [], documento=documento, estrito=True, regras=regras)

    async def exportar_questionario(self, id_questionario):
        async with self.pool.connection() as conn:
            row = (await (await conn.execute('''SELECT documento, codigo, titulo, ativo, algoritmo, exibir_resultado
                FROM questionarios WHERE id_questionario = %s''', (id_questionario,))).fetchone())
            if row is None:
                return None
            if row['documento'] is None:
                raise ValueError('Estrutura JSON ausente. Execute sis-questionario-db para atualizar o banco.')
            # Metadata may also have been changed by an administrator using SQL.
            return validar({**row['documento'], **{key: row[key] for key in
                            ('codigo', 'titulo', 'ativo', 'algoritmo', 'exibir_resultado')}})

    async def exportar_algoritmo(self, id_questionario):
        async with self.pool.connection() as conn:
            row = await (await conn.execute(
                'SELECT algoritmo, regras_algoritmo FROM questionarios WHERE id_questionario = %s',
                (id_questionario,))).fetchone()
            return regras_salvas(row) if row else None

    async def listar_questionarios(self):
        async with self.pool.connection() as conn:
            return (await (await conn.execute('SELECT * FROM questionarios WHERE ativo ORDER BY titulo, id_questionario')).fetchall())

    async def listar_questionarios_admin(self):
        async with self.pool.connection() as conn:
            return (await (await conn.execute('SELECT * FROM questionarios ORDER BY titulo, id_questionario')).fetchall())

    async def resultados_questionario(self, id_questionario, filtros, perfis=None):
        """Apply every selected filter to the same submissions in every chart."""
        async with self.pool.connection() as conn:
            # All charts and totals must describe the same database snapshot.
            (await conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            quiz = (await (await conn.execute('SELECT titulo, algoritmo, exibir_resultado, regras_algoritmo FROM questionarios WHERE id_questionario = %s',
                                (id_questionario,))).fetchone())
            if not quiz:
                return None
            perfis = [] if perfis is None else perfis
            categorias_disponiveis = categorias(quiz)
            if (not isinstance(perfis, list) or any(not isinstance(p, str) or p not in categorias_disponiveis for p in perfis)
                    or (perfis and not quiz['algoritmo'])):
                raise ValueError('Filtro de perfil inválido.')
            perguntas = (await (await conn.execute('SELECT id_pergunta, enunciado FROM perguntas '
                                     'WHERE id_questionario = %s ORDER BY ordem', (id_questionario,))).fetchall())
            opcoes = (await (await conn.execute('''SELECT o.id_opcao, o.id_pergunta, o.texto FROM opcoes o
                JOIN perguntas p USING (id_pergunta) WHERE p.id_questionario = %s
                ORDER BY p.ordem, o.ordem''', (id_questionario,))).fetchall())
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

            total = (await (await conn.execute('SELECT COUNT(*) AS n FROM envios WHERE id_questionario = %s',
                                 (id_questionario,))).fetchone())['n']
            where, params = condicao()
            matching = (await (await conn.execute(sql.SQL('SELECT COUNT(*) AS n FROM envios e WHERE {}').format(where),
                                    params)).fetchone())['n']
            charts = []
            for pergunta in perguntas:
                pid = pergunta['id_pergunta']
                where, params = condicao()
                rows = (await (await conn.execute(sql.SQL('''SELECT r.id_opcao, COUNT(*) AS n FROM respostas r
                    JOIN envios e USING (id_envio) WHERE r.id_pergunta = %s AND {}
                    GROUP BY r.id_opcao''').format(where), [pid, *params])).fetchall())
                counts = {r['id_opcao']: r['n'] for r in rows}
                options = [dict(id=o['id_opcao'], label=o['texto'], count=counts.get(o['id_opcao'], 0),
                                selected=o['id_opcao'] in selecionadas.get(pid, []))
                           for o in opcoes if o['id_pergunta'] == pid]
                charts.append(dict(id=pid, title=pergunta['enunciado'], options=options,
                                   base=sum(o['count'] for o in options)))
            if quiz['algoritmo']:
                rows = (await (await conn.execute(sql.SQL("""SELECT COALESCE(e.resultado->>'category',
                    'sem_classificacao') AS categoria, COUNT(*) AS n FROM envios e
                    WHERE {} GROUP BY categoria""").format(where), params)).fetchall())
                counts = {row['categoria']: row['n'] for row in rows}
                charts.insert(0, dict(id='profiles', title='Perfis dos participantes', base=matching,
                    options=[dict(id=key, label=label, count=counts.get(key, 0), selected=key in perfis)
                             for key, label in categorias_disponiveis.items()]))
            return dict(title=quiz['titulo'], total=total, matching=matching, charts=charts,
                        algorithm=quiz['algoritmo'], show_result=quiz['exibir_resultado'])

    async def carregar_questionario(self, id_questionario):
        async with self.pool.connection() as conn:
            questionario = (await (await conn.execute(
                'SELECT * FROM questionarios WHERE id_questionario = %s AND ativo', (id_questionario,),
            )).fetchone())
            if not questionario:
                return None
            perguntas = (await (await conn.execute(
                'SELECT * FROM perguntas WHERE id_questionario = %s ORDER BY ordem', (id_questionario,),
            )).fetchall())
            opcoes = (await (await conn.execute(
                '''SELECT o.* FROM opcoes o JOIN perguntas p ON p.id_pergunta = o.id_pergunta
                   WHERE p.id_questionario = %s ORDER BY o.ordem''', (id_questionario,),
            )).fetchall())
            por_pergunta = {}
            for opcao in opcoes:
                por_pergunta.setdefault(opcao['id_pergunta'], []).append(opcao)
            for pergunta in perguntas:
                pergunta['opcoes'] = por_pergunta.get(pergunta['id_pergunta'], [])
            questionario['perguntas'] = perguntas
            return questionario

    async def registrar_aluno(self, nome, email):
        nome, email = nome.strip(), email.strip().lower()
        if not nome or not email:
            raise ValueError('Informe nome e e-mail.')
        async with self.pool.connection() as conn:
            aluno = (await (await conn.execute(
                '''INSERT INTO alunos (nome, email) VALUES (%s, %s)
                   ON CONFLICT (email) DO NOTHING RETURNING id_aluno''',
                (nome, email),
            )).fetchone())
            if aluno:
                return aluno['id_aluno']
            return (await (await conn.execute('SELECT id_aluno FROM alunos WHERE email = %s', (email,))).fetchone())['id_aluno']

    async def dispositivo_ja_respondeu(self, id_dispositivo, id_questionario):
        async with self.pool.connection() as conn:
            return (await (await conn.execute(
                'SELECT 1 FROM envios WHERE id_dispositivo = %s AND id_questionario = %s',
                (id_dispositivo, id_questionario),
            )).fetchone()) is not None

    async def registrar_envio(self, id_aluno, id_questionario, respostas, id_dispositivo):
        id_dispositivo = UUID(str(id_dispositivo))
        async with self.pool.connection() as conn:
            questionario = (await (await conn.execute(
                'SELECT id_questionario, algoritmo, regras_algoritmo FROM questionarios WHERE id_questionario = %s AND ativo',
                (id_questionario,),
            )).fetchone())
            if not questionario:
                raise ValueError('Questionário indisponível. Selecione novamente na página inicial.')
            permitidas = (await (await conn.execute(
                '''SELECT p.id_pergunta, p.enunciado, o.id_opcao, o.texto FROM perguntas p
                   JOIN opcoes o ON o.id_pergunta = p.id_pergunta WHERE p.id_questionario = %s''',
                (id_questionario,),
            )).fetchall())
            resultado = resultado_envio(questionario, permitidas, respostas)
            envio = (await (await conn.execute(
                '''INSERT INTO envios (id_aluno, id_questionario, id_dispositivo, resultado)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (id_dispositivo, id_questionario) DO NOTHING RETURNING id_envio''',
                (id_aluno, id_questionario, id_dispositivo, Jsonb(resultado) if resultado else None),
            )).fetchone())
            if not envio:
                raise EnvioDuplicado('Este navegador já respondeu a este questionário.')
            id_envio = envio['id_envio']
            async with conn.cursor() as cur:
                (await cur.executemany(
                    'INSERT INTO respostas (id_envio, id_pergunta, id_opcao) VALUES (%s, %s, %s)',
                    [(id_envio, p, o) for p, o in respostas.items()],
                ))
            return id_envio

    async def carregar_resultado(self, id_envio, id_dispositivo):
        async with self.pool.connection() as conn:
            row = (await (await conn.execute('''SELECT e.resultado, q.algoritmo, q.regras_algoritmo FROM envios e
                JOIN questionarios q USING (id_questionario)
                WHERE e.id_envio = %s AND e.id_dispositivo = %s AND q.exibir_resultado''',
                (id_envio, id_dispositivo))).fetchone())
            return {**row['resultado'], 'profiles': regras_salvas(row)['profiles']} if row and row['resultado'] else None

    async def configurar_devolutiva(self, id_questionario, habilitada):
        async with self.pool.connection() as conn:
            row = (await (await conn.execute('''UPDATE questionarios SET exibir_resultado = %s,
                documento = jsonb_set(documento, '{exibir_resultado}', to_jsonb(%s::boolean))
                WHERE id_questionario = %s AND algoritmo IS NOT NULL RETURNING id_questionario''',
                (habilitada, habilitada, id_questionario))).fetchone())
            if not row:
                raise ValueError('Questionário sem algoritmo de classificação.')
