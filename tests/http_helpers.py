"""Session fixtures for Starlette's signed-cookie format (test code only)."""
import base64
import json
from contextlib import contextmanager

from itsdangerous import TimestampSigner


def use_sync_transaction_fixture(app):
    """Keep legacy HTTP tests inside their uncommitted sync database transaction.

    Real AsyncConnectionPool behavior is tested separately in test_async_database.
    """
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from sis_questionario import bd_exec
    from sis_questionario.bd_async import AsyncDatabase

    methods = {
        name: AsyncMock(side_effect=getattr(bd_exec, name))
        for name in vars(AsyncDatabase)
        if not name.startswith('_') and hasattr(bd_exec, name)
        and callable(getattr(bd_exec, name))
    }
    app.state.database = SimpleNamespace(**methods)


@contextmanager
def session_transaction(client):
    signer = TimestampSigner(client.app.state.settings['SECRET_KEY'])
    cookie = client.cookies.get('session')
    session = json.loads(base64.b64decode(signer.unsign(cookie))) if cookie else {}
    yield session
    for cookie in list(client.cookies.jar):
        if cookie.name == 'session':
            client.cookies.jar.clear(cookie.domain, cookie.path, cookie.name)
    encoded = base64.b64encode(json.dumps(session).encode())
    client.cookies.set('session', signer.sign(encoded).decode(), domain=client.base_url.host + ('.local' if '.' not in client.base_url.host else ''), path='/')
