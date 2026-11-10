"""Local ASGI launcher, including Psycopg-compatible event loops on Windows."""
import asyncio
import os
import sys

import uvicorn

from .config import carregar_configuracao


def loop_factory():
    # Psycopg async connections cannot run on Windows' ProactorEventLoop.
    loop = asyncio.SelectorEventLoop() if sys.platform == 'win32' else asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop


def serve():
    carregar_configuracao()
    workers = int(os.environ.get('WEB_WORKERS', '1'))
    port = int(os.environ.get('PORT', '5000'))
    graceful = int(os.environ.get('WEB_SHUTDOWN_TIMEOUT', '30'))
    reload = os.environ.get('WEB_RELOAD') == '1'
    if workers < 1 or not 1 <= port <= 65535 or graceful < 1:
        raise ValueError('Invalid WEB_WORKERS, PORT or WEB_SHUTDOWN_TIMEOUT.')
    if reload and workers != 1:
        raise ValueError('WEB_RELOAD requires WEB_WORKERS=1.')
    if workers > 1 and len(os.environ.get('SECRET_KEY', '')) < 32:
        raise ValueError('Multiple workers require a stable SECRET_KEY of at least 32 characters.')
    uvicorn.run(
        'sis_questionario.app:create_app', factory=True,
        host=os.environ.get('WEB_HOST', '127.0.0.1'), port=port,
        workers=workers, reload=reload, loop='sis_questionario.server:loop_factory',
        proxy_headers=os.environ.get('TRUST_PROXY') == '1',
        forwarded_allow_ips=os.environ.get('FORWARDED_ALLOW_IPS', '127.0.0.1,::1'),
        timeout_graceful_shutdown=graceful,
    )


if __name__ == '__main__':
    serve()
