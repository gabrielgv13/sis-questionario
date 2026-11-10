"""Pool exclusivo do processo web; ferramentas CLI continuam com conexão direta."""
import atexit
import math
import os

from psycopg.rows import dict_row

from .config import carregar_configuracao, conexao_banco

_pool = None
_pid = None


def obter_pool():
    if _pool is not None and _pid != os.getpid():
        raise RuntimeError('Pool PostgreSQL herdado por fork; inicialize no worker.')
    return _pool


def iniciar_pool():
    global _pool, _pid
    if obter_pool() is not None:
        return
    # Import only after Gunicorn/gevent patches threading, queue and select.
    from psycopg_pool import ConnectionPool

    carregar_configuracao()
    minimum = int(os.environ.get('DB_POOL_MIN_SIZE', '0'))
    maximum = int(os.environ.get('DB_POOL_MAX_SIZE', '2'))
    timeout = float(os.environ.get('DB_POOL_TIMEOUT', '5'))
    waiting = int(os.environ.get('DB_POOL_MAX_WAITING', '32'))
    if not (0 <= minimum <= maximum and maximum >= 1 and math.isfinite(timeout)
            and timeout > 0 and waiting >= 1):
        raise ValueError('Configuração DB_POOL inválida.')
    pool = ConnectionPool(
        kwargs={**conexao_banco(), 'row_factory': dict_row},
        min_size=minimum, max_size=maximum, timeout=timeout,
        max_waiting=waiting, num_workers=1, open=False,
        check=ConnectionPool.check_connection,
    )
    try:
        pool.open()
    except BaseException:
        pool.close()
        raise
    _pool, _pid = pool, os.getpid()


def fechar_pool():
    global _pool, _pid
    pool = obter_pool()
    _pool, _pid = None, None
    if pool is not None:
        pool.close()


atexit.register(fechar_pool)
