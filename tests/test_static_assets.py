"""Verify the styles and scripts exposed by the ASGI application."""
import unittest

from fastapi.testclient import TestClient

from sis_questionario.app import create_app


class StaticAssetsTest(unittest.TestCase):
    def test_login_styles_and_admin_scripts_are_served(self):
        client = TestClient(create_app(), base_url='https://testserver')
        page = client.get('/admin/login')
        self.assertEqual(page.status_code, 200)
        for path, mime, markers in (
            ('css/app.css', 'text/css', ('.min-h-screen', '.bg-teal-800', '.max-w-6xl')),
            ('css/admin.css', 'text/css', ('.admin-card',)),
            ('js/admin.js', 'javascript', ('querySelector',)),
            ('js/admin_questionarios.js', 'javascript', ('querySelector',)),
        ):
            with self.subTest(path=path):
                response = client.get('/static/' + path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(mime, response.headers['content-type'])
                for marker in markers:
                    self.assertIn(marker, response.text)
                if mime == 'text/css':
                    self.assertIn('https://testserver/static/' + path, page.text)
