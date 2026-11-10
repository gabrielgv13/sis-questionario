"""Isolated integration probe, invoked by test_worker_config on Unix."""
from gevent import monkey
monkey.patch_all()

import os
import gevent
from psycopg_pool import ConnectionPool, PoolTimeout

from sis_questionario import gunicorn_config

gunicorn_config.post_worker_init(None)
gunicorn_config.worker_exit(None, None)

with ConnectionPool(os.environ['TEST_DATABASE_URL'], min_size=1, max_size=1, timeout=2) as pool:
    pool.wait(timeout=10)
    ticks = []

    def ticker():
        for _ in range(20):
            gevent.sleep(0.01)
            ticks.append(1)

    def query():
        with pool.connection() as conn:
            conn.execute('SELECT pg_sleep(0.4)')
            assert len(ticks) >= 10, 'database I/O blocked greenlets'

    greenlets = [gevent.spawn(query), gevent.spawn(query), gevent.spawn(ticker)]
    gevent.joinall(greenlets, timeout=5, raise_error=True)
    assert all(g.ready() for g in greenlets), 'query/pool waits deadlocked'
    assert len(ticks) == 20, 'database I/O blocked greenlets'
    # An independent waiter must time out while another greenlet owns the only connection.
    with pool.connection():
        def exhaust():
            try:
                with pool.connection(timeout=0.1):
                    raise AssertionError('pool exceeded bound')
            except PoolTimeout:
                return True
        waiter = gevent.spawn(exhaust)
        assert waiter.get(timeout=1) is True, 'pool wait blocked hub'
