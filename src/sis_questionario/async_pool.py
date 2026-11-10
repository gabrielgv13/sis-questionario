"""Per-application async pool; CLI and legacy container pools stay independent."""
import math
import os
from contextlib import asynccontextmanager

from fastapi import Request
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .bd_async import AsyncDatabase
from .config import conexao_banco


def create_pool():
    minimum = int(os.environ.get('DB_POOL_MIN_SIZE', '0'))
    maximum = int(os.environ.get('DB_POOL_MAX_SIZE', '2'))
    timeout = float(os.environ.get('DB_POOL_TIMEOUT', '5'))
    waiting = int(os.environ.get('DB_POOL_MAX_WAITING', '32'))
    if not (0 <= minimum <= maximum and maximum >= 1 and math.isfinite(timeout)
            and timeout > 0 and waiting >= 1):
        raise ValueError('Invalid DB_POOL configuration.')
    return AsyncConnectionPool(
        kwargs={**conexao_banco(), 'row_factory': dict_row},
        min_size=minimum, max_size=maximum, timeout=timeout, max_waiting=waiting,
        open=False, check=AsyncConnectionPool.check_connection,
    )


@asynccontextmanager
async def lifespan(app):
    pool = create_pool()
    app.state.pool = pool
    app.state.database = AsyncDatabase(pool)
    try:
        await pool.open()
        yield
    finally:
        await pool.close()
        app.state.pool = None
        app.state.database = AsyncDatabase(None)


async def get_database(request: Request) -> AsyncDatabase:
    return request.app.state.database
