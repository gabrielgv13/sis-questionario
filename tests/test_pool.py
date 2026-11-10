import os
import unittest
from unittest.mock import patch

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout

from sis_questionario import bd_exec as db


class PoolLifecycleTest(unittest.TestCase):
    def test_cli_uses_direct_connection(self):
        with patch.object(db.psycopg, 'connect') as connect:
            db.conectar()
        connect.assert_called_once()


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Configure TEST_DATABASE_URL.')
class PoolTransactionTest(unittest.TestCase):
    def setUp(self):
        self.pool = ConnectionPool(os.environ['TEST_DATABASE_URL'], min_size=1, max_size=1,
                                   timeout=0.1, open=True)
        self.addCleanup(self.pool.close)
        self.pool.wait(timeout=10)

    def test_reuse_commit_rollback_and_recovery(self):
        with self.pool.connection() as conn:
            conn.execute('CREATE TEMP TABLE pool_transaction_test (value int)')
            conn.execute('INSERT INTO pool_transaction_test VALUES (1)')
            pid = conn.info.backend_pid
        with self.assertRaises(ValueError):
            with self.pool.connection() as conn:
                conn.execute('INSERT INTO pool_transaction_test VALUES (2)')
                raise ValueError('rollback')
        with self.assertRaises(psycopg.errors.DivisionByZero):
            with self.pool.connection() as conn:
                conn.execute('SELECT 1 / 0')
        with self.pool.connection() as conn:
            self.assertEqual(conn.info.backend_pid, pid)
            self.assertEqual(conn.execute('SELECT value FROM pool_transaction_test').fetchall(), [(1,)])

    def test_exhaustion_returns_connection_after_timeout(self):
        with self.pool.connection():
            with self.assertRaises(PoolTimeout):
                with self.pool.connection():
                    self.fail('pool exceeded maximum')
        with self.pool.connection() as conn:
            self.assertEqual(conn.execute('SELECT 1').fetchone(), (1,))
