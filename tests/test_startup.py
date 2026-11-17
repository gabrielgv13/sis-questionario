import os
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from sis_questionario import main, main_perfil
from sis_questionario import bd_exec as db
from sis_questionario.perfis import VERSAO, VERSAO_ANTERIOR
from sis_questionario.questionario_json import validar


class StartupUnitTest(unittest.TestCase):
    def test_default_prepares_database_without_loading_profile(self):
        with patch('sis_questionario.setup_db.main') as prepare, patch.object(db, 'inicializar_banco') as seed, patch('sis_questionario.server.serve') as serve:
            main()
            prepare.assert_called_once_with()
            seed.assert_not_called()
            serve.assert_called_once_with()

    def test_profile_prepares_before_loading_and_serving(self):
        actions = []
        with patch('sis_questionario.setup_db.main', side_effect=lambda: actions.append('prepare')), patch.object(db, 'inicializar_banco', side_effect=lambda: actions.append('profile')), patch('sis_questionario.server.serve') as serve:
            serve.side_effect = lambda: actions.append('serve')
            main_perfil()
        self.assertEqual(actions, ['prepare', 'profile', 'serve'])

    def test_previous_json_identifier_is_normalized(self):
        path = Path(__file__).resolve().parents[1] / 'docs/questionario_perfil.json'
        import json
        document = json.loads(path.read_text(encoding='utf-8'))
        document['algoritmo'] = VERSAO_ANTERIOR
        self.assertEqual(validar(document)['algoritmo'], VERSAO)


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Configure TEST_DATABASE_URL.')
class StartupDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(os.environ['TEST_DATABASE_URL'], autocommit=True, row_factory=dict_row)
        self.addCleanup(self.conn.close)
        self.schema = 'startup_test_' + uuid.uuid4().hex
        self.conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.addCleanup(self.cleanup_schema)
        self.conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(self.schema)))
        script = Path(db.__file__).with_name('banco.sql').read_text(encoding='utf-8')
        self.structure = script.split('-- INICIO_TABELAS')[1].split('-- FIM_TABELAS')[0]

        @contextmanager
        def connect():
            with self.conn.transaction():
                yield self.conn

        patcher = patch.object(db, 'conectar', connect)
        patcher.start()
        self.addCleanup(patcher.stop)
        prepare = patch('sis_questionario.setup_db.main', side_effect=lambda: self.conn.execute(self.structure))
        prepare.start()
        self.addCleanup(prepare.stop)
        serve = patch('sis_questionario.server.serve')
        serve.start()
        self.addCleanup(serve.stop)

    def cleanup_schema(self):
        self.conn.execute('ROLLBACK')
        self.conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))

    def count(self, table):
        return self.conn.execute(sql.SQL('SELECT COUNT(*) AS n FROM {}').format(sql.Identifier(table))).fetchone()['n']

    def test_clean_then_profile_then_restart_preserves_data(self):
        main()
        self.assertTrue(all(self.count(table) == 0 for table in ['questionarios','alunos','perguntas','opcoes','envios','respostas']))
        main_perfil()
        main_perfil()
        self.assertEqual(self.count('questionarios'), 1)
        self.assertEqual(self.count('perguntas'), 11)
        self.assertEqual(self.count('alunos'), 0)
        aluno = db.registrar_aluno('Teste', 'startup@example.com')
        quiz = db.carregar_questionario(db.listar_questionarios()[0]['id_questionario'])
        answers = {p['id_pergunta']: p['opcoes'][0]['id_opcao'] for p in quiz['perguntas']}
        db.registrar_envio(aluno, quiz['id_questionario'], answers, uuid.uuid4())
        main()
        self.assertEqual(self.count('envios'), 1)
        self.assertEqual(self.count('respostas'), 11)
        self.assertEqual(self.count('questionarios'), 1)

    def test_migration_changes_only_historical_identifier(self):
        main_perfil()
        self.conn.execute('''UPDATE questionarios SET algoritmo = %s,
            documento = jsonb_set(documento, '{algoritmo}', %s)''', (VERSAO_ANTERIOR, Jsonb(VERSAO_ANTERIOR)))
        aluno = db.registrar_aluno('Teste', 'migration@example.com')
        quiz = db.listar_questionarios()[0]['id_questionario']
        original = dict(version=VERSAO_ANTERIOR, scores={'esportes': 140}, winners=['esportes'], category='esportes')
        self.conn.execute('INSERT INTO envios (id_aluno, id_questionario, resultado) VALUES (%s,%s,%s)', (aluno, quiz, Jsonb(original)))
        main()
        saved = self.conn.execute('SELECT resultado FROM envios').fetchone()['resultado']
        self.assertEqual(saved, {**original, 'version': VERSAO})
        row = self.conn.execute('SELECT algoritmo, documento FROM questionarios').fetchone()
        self.assertEqual(row['algoritmo'], VERSAO)
        self.assertEqual(row['documento']['algoritmo'], VERSAO)
