"""Async PostgreSQL repository. Each operation owns its transaction and connection."""
from uuid import UUID

from psycopg import sql
from psycopg.types.json import Jsonb

from .sync_database import DuplicateSubmission, DuplicateQuestionnaire
from .submission_processing import score_submission
from .scoring_rules import get_category_labels, resolve_import_rules, get_stored_rules
from .questionnaire_import import build_questionnaire_document, validate_questionnaire


class AsyncDatabase:
    DuplicateSubmission = DuplicateSubmission
    DuplicateQuestionnaire = DuplicateQuestionnaire

    def __init__(self, pool):
        self.pool = pool

    async def check_health(self):
        async with self.pool.connection() as conn:
            await conn.execute('SELECT 1 FROM questionarios LIMIT 1')

    async def register_questionnaire(self, code, title, questions, *, document=None, reject_duplicates=False, rules=None):
        """Register a questionnaire once per code and preserve its existing questions."""
        document = build_questionnaire_document(code, title, questions, document)
        rules = resolve_import_rules(document, rules, allow_builtin_rules=not reject_duplicates)
        async with self.pool.connection() as conn:
            questionnaire = (await (await conn.execute(
                '''INSERT INTO questionarios (codigo, titulo, ativo, algoritmo, exibir_resultado, documento, regras_algoritmo)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (codigo) DO NOTHING RETURNING id_questionario''',
                (document['codigo'], document['titulo'], document['ativo'], document['algoritmo'],
                 document['exibir_resultado'], Jsonb(document), Jsonb(rules) if rules else None),
            )).fetchone())
            if not questionnaire:
                if reject_duplicates:
                    raise DuplicateQuestionnaire('Já existe um questionário com esse código. Altere o campo codigo no arquivo para importar uma cópia.')
                return (await (await conn.execute(
                    'SELECT id_questionario FROM questionarios WHERE codigo = %s', (code,),
                )).fetchone())['id_questionario']
            questionnaire_id = questionnaire['id_questionario']
            for position, question in enumerate(document['perguntas'], 1):
                question_id = (await (await conn.execute(
                    '''INSERT INTO perguntas (id_questionario, enunciado, ordem)
                       VALUES (%s, %s, %s) RETURNING id_pergunta''',
                    (questionnaire_id, question['enunciado'], position),
                )).fetchone())['id_pergunta']
                async with conn.cursor() as cur:
                    (await cur.executemany(
                        'INSERT INTO opcoes (id_pergunta, texto, ordem) VALUES (%s, %s, %s)',
                        [(question_id, option_text, i) for i, option_text in enumerate(question['opcoes'], 1)],
                    ))
            return questionnaire_id

    async def import_questionnaire(self, document, rules=None):
        document = validate_questionnaire(document)
        return await self.register_questionnaire(document['codigo'], document['titulo'], [], document=document, reject_duplicates=True, rules=rules)

    async def export_questionnaire(self, questionnaire_id):
        async with self.pool.connection() as conn:
            row = (await (await conn.execute('''SELECT documento, codigo, titulo, ativo, algoritmo, exibir_resultado
                FROM questionarios WHERE id_questionario = %s''', (questionnaire_id,))).fetchone())
            if row is None:
                return None
            if row['documento'] is None:
                raise ValueError('Estrutura JSON ausente. Execute sis-questionario-db para atualizar o banco.')
            # Metadata may also have been changed by an administrator using SQL.
            return validate_questionnaire({**row['documento'], **{key: row[key] for key in
                            ('codigo', 'titulo', 'ativo', 'algoritmo', 'exibir_resultado')}})

    async def export_scoring_rules(self, questionnaire_id):
        async with self.pool.connection() as conn:
            row = await (await conn.execute(
                'SELECT algoritmo, regras_algoritmo FROM questionarios WHERE id_questionario = %s',
                (questionnaire_id,))).fetchone()
            return get_stored_rules(row) if row else None

    async def list_active_questionnaires(self):
        async with self.pool.connection() as conn:
            return (await (await conn.execute('SELECT * FROM questionarios WHERE ativo ORDER BY titulo, id_questionario')).fetchall())

    async def list_all_questionnaires(self):
        async with self.pool.connection() as conn:
            return (await (await conn.execute('SELECT * FROM questionarios ORDER BY titulo, id_questionario')).fetchall())

    async def get_questionnaire_results(self, questionnaire_id, filters, profile_filters=None):
        """Apply every selected filter to the same submissions in every chart."""
        async with self.pool.connection() as conn:
            # All charts and totals must describe the same database snapshot.
            (await conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            quiz = (await (await conn.execute('SELECT titulo, algoritmo, exibir_resultado, regras_algoritmo FROM questionarios WHERE id_questionario = %s',
                                (questionnaire_id,))).fetchone())
            if not quiz:
                return None
            profile_filters = [] if profile_filters is None else profile_filters
            category_labels = get_category_labels(quiz)
            if (not isinstance(profile_filters, list) or any(not isinstance(p, str) or p not in category_labels for p in profile_filters)
                    or (profile_filters and not quiz['algoritmo'])):
                raise ValueError('Filtro de perfil inválido.')
            questions = (await (await conn.execute('SELECT id_pergunta, enunciado FROM perguntas '
                                     'WHERE id_questionario = %s ORDER BY ordem', (questionnaire_id,))).fetchall())
            option_rows = (await (await conn.execute('''SELECT o.id_opcao, o.id_pergunta, o.texto FROM opcoes o
                JOIN perguntas p USING (id_pergunta) WHERE p.id_questionario = %s
                ORDER BY p.ordem, o.ordem''', (questionnaire_id,))).fetchall())
            valid_option_ids = {}
            for option in option_rows:
                valid_option_ids.setdefault(option['id_pergunta'], set()).add(option['id_opcao'])
            selected_options = {}
            for filter_key, option_ids in filters.items():
                if not isinstance(filter_key, str) or not filter_key.isdecimal() or not isinstance(option_ids, list):
                    raise ValueError('Filtros inválidos.')
                question = int(filter_key)
                if (str(question) != filter_key or question not in valid_option_ids or
                        any(type(v) is not int or v not in valid_option_ids[question] for v in option_ids)):
                    raise ValueError('Opção não pertence à pergunta ou ao questionário.')
                if option_ids:
                    selected_options[question] = list(set(option_ids))

            def build_filter_condition():
                conditions = [sql.SQL('e.id_questionario = %s')]
                params = [questionnaire_id]
                if profile_filters:
                    conditions.append(sql.SQL("COALESCE(e.resultado->>'category', 'sem_classificacao') = ANY(%s)"))
                    params.append(profile_filters)
                for question, option_ids in selected_options.items():
                    conditions.append(sql.SQL('''EXISTS (SELECT 1 FROM respostas f
                        WHERE f.id_envio = e.id_envio AND f.id_pergunta = %s
                        AND f.id_opcao = ANY(%s))'''))
                    params.extend([question, option_ids])
                return sql.SQL(' AND ').join(conditions), params

            total = (await (await conn.execute('SELECT COUNT(*) AS n FROM envios WHERE id_questionario = %s',
                                 (questionnaire_id,))).fetchone())['n']
            where, params = build_filter_condition()
            matching = (await (await conn.execute(sql.SQL('SELECT COUNT(*) AS n FROM envios e WHERE {}').format(where),
                                    params)).fetchone())['n']
            charts = []
            for question in questions:
                pid = question['id_pergunta']
                rows = (await (await conn.execute(sql.SQL('''SELECT r.id_opcao, COUNT(*) AS n FROM respostas r
                    JOIN envios e USING (id_envio) WHERE r.id_pergunta = %s AND {}
                    GROUP BY r.id_opcao''').format(where), [pid, *params])).fetchall())
                counts = {r['id_opcao']: r['n'] for r in rows}
                options = [dict(id=o['id_opcao'], label=o['texto'], count=counts.get(o['id_opcao'], 0),
                                selected=o['id_opcao'] in selected_options.get(pid, []))
                           for o in option_rows if o['id_pergunta'] == pid]
                charts.append(dict(id=pid, title=question['enunciado'], options=options,
                                   base=sum(o['count'] for o in options)))
            if quiz['algoritmo']:
                rows = (await (await conn.execute(sql.SQL("""SELECT COALESCE(e.resultado->>'category',
                    'sem_classificacao') AS categoria, COUNT(*) AS n FROM envios e
                    WHERE {} GROUP BY categoria""").format(where), params)).fetchall())
                counts = {row['categoria']: row['n'] for row in rows}
                charts.insert(0, dict(id='profiles', title='Perfis dos participantes', base=matching,
                    options=[dict(id=key, label=label, count=counts.get(key, 0), selected=key in profile_filters)
                             for key, label in category_labels.items()]))
            return dict(title=quiz['titulo'], total=total, matching=matching, charts=charts,
                        algorithm=quiz['algoritmo'], show_result=quiz['exibir_resultado'])

    async def get_active_questionnaire(self, questionnaire_id):
        async with self.pool.connection() as conn:
            questionnaire = (await (await conn.execute(
                'SELECT * FROM questionarios WHERE id_questionario = %s AND ativo', (questionnaire_id,),
            )).fetchone())
            if not questionnaire:
                return None
            questions = (await (await conn.execute(
                'SELECT * FROM perguntas WHERE id_questionario = %s ORDER BY ordem', (questionnaire_id,),
            )).fetchall())
            options = (await (await conn.execute(
                '''SELECT o.* FROM opcoes o JOIN perguntas p ON p.id_pergunta = o.id_pergunta
                   WHERE p.id_questionario = %s ORDER BY o.ordem''', (questionnaire_id,),
            )).fetchall())
            options_by_question = {}
            for option in options:
                options_by_question.setdefault(option['id_pergunta'], []).append(option)
            for question in questions:
                question['opcoes'] = options_by_question.get(question['id_pergunta'], [])
            questionnaire['perguntas'] = questions
            return questionnaire

    async def register_participant(self, name, email):
        name, email = name.strip(), email.strip().lower()
        if not name or not email:
            raise ValueError('Informe nome e e-mail.')
        async with self.pool.connection() as conn:
            participant = (await (await conn.execute(
                '''INSERT INTO alunos (nome, email) VALUES (%s, %s)
                   ON CONFLICT (email) DO NOTHING RETURNING id_aluno''',
                (name, email),
            )).fetchone())
            if participant:
                return participant['id_aluno']
            return (await (await conn.execute('SELECT id_aluno FROM alunos WHERE email = %s', (email,))).fetchone())['id_aluno']

    async def has_device_submitted(self, device_id, questionnaire_id):
        async with self.pool.connection() as conn:
            return (await (await conn.execute(
                'SELECT 1 FROM envios WHERE id_dispositivo = %s AND id_questionario = %s',
                (device_id, questionnaire_id),
            )).fetchone()) is not None

    async def save_submission(self, participant_id, questionnaire_id, answers, device_id):
        device_id = UUID(str(device_id))
        async with self.pool.connection() as conn:
            questionnaire = (await (await conn.execute(
                'SELECT id_questionario, algoritmo, regras_algoritmo FROM questionarios WHERE id_questionario = %s AND ativo',
                (questionnaire_id,),
            )).fetchone())
            if not questionnaire:
                raise ValueError('Questionário indisponível. Selecione novamente na página inicial.')
            allowed_options = (await (await conn.execute(
                '''SELECT p.id_pergunta, p.enunciado, o.id_opcao, o.texto FROM perguntas p
                   JOIN opcoes o ON o.id_pergunta = p.id_pergunta WHERE p.id_questionario = %s''',
                (questionnaire_id,),
            )).fetchall())
            result = score_submission(questionnaire, allowed_options, answers)
            submission = (await (await conn.execute(
                '''INSERT INTO envios (id_aluno, id_questionario, id_dispositivo, resultado)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (id_dispositivo, id_questionario) DO NOTHING RETURNING id_envio''',
                (participant_id, questionnaire_id, device_id, Jsonb(result) if result else None),
            )).fetchone())
            if not submission:
                raise DuplicateSubmission('Este navegador já respondeu a este questionário.')
            submission_id = submission['id_envio']
            async with conn.cursor() as cur:
                (await cur.executemany(
                    'INSERT INTO respostas (id_envio, id_pergunta, id_opcao) VALUES (%s, %s, %s)',
                    [(submission_id, p, o) for p, o in answers.items()],
                ))
            return submission_id

    async def get_submission_result(self, submission_id, device_id):
        async with self.pool.connection() as conn:
            row = (await (await conn.execute('''SELECT e.resultado, q.algoritmo, q.regras_algoritmo FROM envios e
                JOIN questionarios q USING (id_questionario)
                WHERE e.id_envio = %s AND e.id_dispositivo = %s AND q.exibir_resultado''',
                (submission_id, device_id))).fetchone())
            return {**row['resultado'], 'profiles': get_stored_rules(row)['profiles']} if row and row['resultado'] else None

    async def set_feedback_enabled(self, questionnaire_id, enabled):
        async with self.pool.connection() as conn:
            row = (await (await conn.execute('''UPDATE questionarios SET exibir_resultado = %s,
                documento = jsonb_set(documento, '{exibir_resultado}', to_jsonb(%s::boolean))
                WHERE id_questionario = %s AND algoritmo IS NOT NULL RETURNING id_questionario''',
                (enabled, enabled, questionnaire_id))).fetchone())
            if not row:
                raise ValueError('Questionário sem algoritmo de classificação.')

    async def set_questionnaire_visibility(self, questionnaire_id, visible):
        async with self.pool.connection() as conn:
            row = await (await conn.execute(
                """UPDATE questionarios SET ativo = %s,
                documento = jsonb_set(documento, '{ativo}', to_jsonb(%s::boolean))
                WHERE id_questionario = %s RETURNING id_questionario""",
                (visible, visible, questionnaire_id))).fetchone()
            return row is not None
