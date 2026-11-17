"""Deployment invariants which can also be checked without Docker installed."""
import os
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import patch

from psycopg.conninfo import conninfo_to_dict
import yaml

ROOT = Path(__file__).resolve().parents[1]


class ContainerConfigurationTest(unittest.TestCase):
    def test_stack_preserves_volumes_and_provisioning_barrier(self):
        config = yaml.safe_load((ROOT / 'compose.yaml').read_text(encoding='utf-8'))
        self.assertEqual(set(config['volumes']), {'clean-db', 'test-db', 'clean-secrets', 'test-secrets'})
        for variant in ('clean', 'test'):
            web = config['services']['web-' + variant]
            prepare = config['services']['prepare-' + variant]
            self.assertEqual(web['depends_on']['prepare-' + variant]['condition'], 'service_completed_successfully')
            self.assertEqual(prepare['depends_on']['db-' + variant]['condition'], 'service_healthy')
            self.assertEqual(web['environment']['WEB_HOST'], '0.0.0.0')
            self.assertEqual(web['environment']['WEB_RELOAD'], '0')
            self.assertNotIn('DB_ADMIN_PASSWORD', web['environment'])
            self.assertTrue(web['read_only'])
            self.assertIn(f'{variant}-secrets:/secrets:ro', web['volumes'])
            self.assertIn('stop_grace_period', web)

    def test_validation_target_has_separate_image(self):
        config = yaml.safe_load((ROOT / 'compose.validation.yaml').read_text(encoding='utf-8'))
        validation = config['services']['validate']
        self.assertEqual(validation['profiles'], ['validation'])
        self.assertEqual(validation['build']['target'], 'validation')
        self.assertEqual(validation['networks'], ['clean'])

    def test_validation_launcher_escapes_database_password(self):
        password = "test:@ /'password"
        env = {'DB_HOST': 'db-clean', 'DB_NAME': 'test', 'DB_ADMIN_USER': 'owner', 'DB_ADMIN_PASSWORD': password}
        with patch.dict(os.environ, env, clear=True), patch('os.execvp') as execute:
            runpy.run_path(str(ROOT / 'images/common/validate.py'))
            self.assertEqual(conninfo_to_dict(os.environ['TEST_DATABASE_URL'])['password'], password)
            self.assertEqual(execute.call_args.args[1], [sys.executable, '-m', 'unittest', 'discover', '-s', '/app/tests', '-v'])
