import os
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from sis_questionario.perfis import classificar


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Configure TEST_DATABASE_URL.')
class PopularPerfilTest(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(os.environ['TEST_DATABASE_URL'], autocommit=True, row_factory=dict_row)
        self.addCleanup(self.conn.close)
        self.schema = 'seed_test_' + uuid.uuid4().hex
        self.conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.addCleanup(self.cleanup_schema)
        self.conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(self.schema)))
        root = Path(__file__).resolve().parents[1]
        structure = (root / 'src/sis_questionario/banco.sql').read_text(encoding='utf-8')
        self.conn.execute(structure.split('-- INICIO_TABELAS')[1].split('-- FIM_TABELAS')[0])
        self.script = (root / 'docs/popular_perfil.sql').read_text(encoding='utf-8').replace(
            'SET LOCAL search_path TO public;', f'SET LOCAL search_path TO {self.schema};')

    def cleanup_schema(self):
        self.conn.execute('ROLLBACK')
        self.conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))

    def test_snapshots_match_classifier_and_rerun_preserves_configuration(self):
        self.conn.execute(self.script)
        from sis_questionario.questionario_json import validar
        documento = self.conn.execute('SELECT documento FROM questionarios').fetchone()['documento']
        self.assertEqual(len(validar(documento)['perguntas']), 11)
        rows = self.conn.execute('''SELECT e.id_envio, e.resultado,
            jsonb_object_agg(p.enunciado, o.texto) AS respostas FROM envios e
            JOIN respostas r USING (id_envio) JOIN perguntas p USING (id_pergunta)
            JOIN opcoes o USING (id_opcao) GROUP BY e.id_envio''').fetchall()
        self.assertEqual(len(rows), 120)
        for row in rows:
            self.assertEqual(row['resultado'], classificar(row['respostas']))
        self.conn.execute('UPDATE questionarios SET exibir_resultado = FALSE')
        self.conn.execute(self.script)
        self.assertFalse(self.conn.execute('SELECT exibir_resultado FROM questionarios').fetchone()['exibir_resultado'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) AS n FROM respostas').fetchone()['n'], 1320)
        after = self.conn.execute('SELECT id_envio, resultado FROM envios').fetchall()
        self.assertEqual({r['id_envio']: r['resultado'] for r in after}, {r['id_envio']: r['resultado'] for r in rows})

    def test_backfill_only_matching_examples_preserves_existing_results(self):
        self.conn.execute(self.script)
        self.conn.execute('UPDATE envios SET resultado = NULL WHERE id_envio IN (1,2)')
        self.conn.execute("UPDATE envios SET resultado = resultado || '{\"marker\":true}'::jsonb WHERE id_envio = 3")
        self.conn.execute('''UPDATE respostas r SET id_opcao = o.id_opcao FROM opcoes o,
            perguntas p WHERE r.id_envio = 2 AND p.ordem = 1 AND r.id_pergunta = p.id_pergunta
            AND o.id_pergunta = p.id_pergunta AND o.ordem = 1''')
        self.conn.execute('''INSERT INTO envios (id_aluno,id_questionario,id_dispositivo)
            SELECT id_aluno,id_questionario,%s FROM envios WHERE id_envio = 1''', (uuid.uuid4(),))
        self.conn.execute(self.script)
        results = {r['id_envio']: r['resultado'] for r in self.conn.execute('SELECT id_envio,resultado FROM envios')}
        self.assertIsNotNone(results[1])
        self.assertIsNone(results[2])
        self.assertTrue(results[3]['marker'])
        self.assertEqual(sum(value is None for value in results.values()), 2)
