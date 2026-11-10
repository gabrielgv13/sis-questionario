import os
import unittest
from unittest.mock import patch

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout

from sis_questionario import bd_exec as db, database_pool as pools


class PoolLifecycleTest(unittest.TestCase):
    def tearDown(self):
        pools.fechar_pool()

    def test_cli_uses_direct_connection(self):
        with patch.object(db.psycopg, 'connect') as connect:
            db.conectar()
        connect.assert_called_once()

    def test_web_pool_is_bounded_and_closed(self):
        with patch.dict(os.environ, {}, clear=True), patch('psycopg_pool.ConnectionPool') as factory:
            pools.iniciar_pool()
            pools.iniciar_pool()
            self.assertEqual(factory.call_count, 1)
            self.assertEqual(factory.call_args.kwargs['max_size'], 2)
            self.assertEqual(factory.call_args.kwargs['min_size'], 0)
            self.assertEqual(factory.call_args.kwargs['max_waiting'], 32)
            self.assertFalse(factory.call_args.kwargs['open'])
            self.assertIs(db.conectar(), factory.return_value.connection.return_value)
            pools.fechar_pool()
            factory.return_value.close.assert_called_once()

    def test_invalid_configuration_and_inherited_pool(self):
        with patch.dict(os.environ, {'DB_POOL_MAX_SIZE': '0'}):
            with self.assertRaises(ValueError):
                pools.iniciar_pool()
        with patch.object(pools, '_pool', object()), patch.object(pools, '_pid', -1):
            with self.assertRaisesRegex(RuntimeError, 'fork'):
                pools.obter_pool()


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
