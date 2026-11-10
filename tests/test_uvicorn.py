import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from psycopg_pool import PoolTimeout

from sis_questionario.app import create_app
from sis_questionario.async_pool import create_pool, lifespan
from sis_questionario.bd_async import AsyncDatabase
from sis_questionario.server import loop_factory, serve
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware


class ServerConfigurationTest(unittest.TestCase):
    def test_launcher_and_explicit_windows_loop(self):
        with patch.dict(os.environ, {}, clear=True), patch('sis_questionario.server.carregar_configuracao'), patch('sis_questionario.server.uvicorn.run') as run:
            serve()
        self.assertEqual(run.call_args.args, ('sis_questionario.app:create_app',))
        self.assertEqual(run.call_args.kwargs['port'], 5000)
        self.assertTrue(run.call_args.kwargs['factory'])
        self.assertFalse(run.call_args.kwargs['proxy_headers'])
        with patch('sis_questionario.server.sys.platform', 'win32'):
            loop = loop_factory()
        try:
            self.assertIsInstance(loop, asyncio.SelectorEventLoop)
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    def test_worker_secret_and_reload_validation(self):
        for env in [{'WEB_WORKERS': '0'}, {'WEB_WORKERS': '2', 'SECRET_KEY': ''},
                    {'WEB_WORKERS': '2', 'WEB_RELOAD': '1'}, {'PORT': '65536'}]:
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True), patch('sis_questionario.server.carregar_configuracao'):
                with self.assertRaises(ValueError):
                    serve()

    def test_proxy_configuration(self):
        with patch.dict(os.environ, {'TRUST_PROXY': '1', 'FORWARDED_ALLOW_IPS': '10.0.0.1'}, clear=True), patch('sis_questionario.server.carregar_configuracao'), patch('sis_questionario.server.uvicorn.run') as run:
            serve()
        self.assertTrue(run.call_args.kwargs['proxy_headers'])
        self.assertEqual(run.call_args.kwargs['forwarded_allow_ips'], '10.0.0.1')

    def test_pool_errors_are_private_503(self):
        with patch.object(AsyncDatabase, 'listar_questionarios', side_effect=PoolTimeout('private')):
            response = TestClient(create_app()).get('/')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private', response.text)

    def test_async_pool_configuration(self):
        with patch.dict(os.environ, {}, clear=True), patch('sis_questionario.async_pool.AsyncConnectionPool') as factory:
            create_pool()
        self.assertFalse(factory.call_args.kwargs['open'])
        self.assertEqual(factory.call_args.kwargs['max_size'], 2)
        with patch.dict(os.environ, {'DB_POOL_MAX_SIZE': '0'}), self.assertRaises(ValueError):
            create_pool()

    def test_forwarded_scheme_only_from_trusted_peer(self):
        app = ProxyHeadersMiddleware(create_app(), trusted_hosts=['127.0.0.1'])
        for peer, scheme in [('127.0.0.1', 'https'), ('203.0.113.1', 'http')]:
            client = TestClient(app, client=(peer, 12345))
            response = client.get('/admin/login', headers={'X-Forwarded-Proto': 'https'})
            self.assertIn(scheme + '://testserver', response.text)


class LifespanTest(unittest.IsolatedAsyncioTestCase):
    async def test_pool_cleanup_after_exception_and_independent_apps(self):
        pools = [MagicMock(open=AsyncMock(), close=AsyncMock()) for _ in range(2)]
        first, second = create_app(), create_app()
        with patch('sis_questionario.async_pool.create_pool', side_effect=pools):
            with self.assertRaises(ValueError):
                async with lifespan(first), lifespan(second):
                    self.assertIsNot(first.state.pool, second.state.pool)
                    raise ValueError('request failure')
        for pool in pools:
            pool.open.assert_awaited_once()
            pool.close.assert_awaited_once()
        self.assertIsNone(first.state.pool)


class UvicornProcessTest(unittest.TestCase):
    def test_real_server_single_worker_multiple_workers_and_reload(self):
        for workers, reload in [('1', '0'), ('2', '0'), ('1', '1')]:
            with self.subTest(workers=workers, reload=reload):
                self.run_server(workers, reload)

    def run_server(self, workers, reload):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = {**os.environ, 'PORT': str(port), 'WEB_HOST': '127.0.0.1',
               'WEB_WORKERS': workers, 'WEB_RELOAD': reload, 'TRUST_PROXY': '1',
               'FORWARDED_ALLOW_IPS': '127.0.0.1', 'COOKIE_SECURE': '0',
               'SECRET_KEY': 'test-server-secret-key-' * 3,
               'ADMIN_PASSWORD': 'test-admin', 'ADMIN_PASSWORD_HASH': '', 'DB_POOL_MIN_SIZE': '0'}
        with tempfile.TemporaryFile(mode='w+') as log:
            process = subprocess.Popen([sys.executable, '-m', 'sis_questionario.server'],
                env=env, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        request = urllib.request.Request(f'http://127.0.0.1:{port}/admin/login',
                            headers={'X-Forwarded-Proto': 'https'})
                        with urllib.request.urlopen(request, timeout=1) as response:
                            self.assertEqual(response.status, 200)
                            self.assertIn(b'https://127.0.0.1', response.read())
                        break
                    except (OSError, urllib.error.URLError):
                        time.sleep(.1)
                else:
                    log.seek(0)
                    self.fail('Uvicorn did not start: ' + log.read())
            finally:
                # SIGTERM is graceful on Unix. Windows terminate kills the supervisor;
                # multi-process startup/shutdown is tested in-process on that platform.
                if sys.platform == 'win32':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    process.terminate()
                process.wait(timeout=15)
