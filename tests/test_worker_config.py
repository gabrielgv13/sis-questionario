import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from sis_questionario import gunicorn_config as config


class WorkerConfigurationTest(unittest.TestCase):
    def test_rounding(self):
        for cores, expected in [(0.1, 1), (0.5, 1), (1, 2), (1.9, 2), (2, 3)]:
            with self.subTest(cores=cores), patch.object(config, 'effective_cpus', return_value=cores):
                self.assertEqual(config.default_workers(), expected)

    def test_quota_hierarchy_and_unlimited(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            membership = root / 'membership'
            membership.write_text('0::/parent/child\n')
            (root / 'parent/child').mkdir(parents=True)
            (root / 'cpu.max').write_text('max 100000')
            (root / 'parent/cpu.max').write_text('10000 100000')
            (root / 'parent/child/cpu.max').write_text('200000 100000')
            self.assertEqual(config.effective_cpus(root, membership), 0.1)

    def test_v1_and_explicit_cpu_budget(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            (root / 'cpu').mkdir()
            (root / 'cpu/cpu.cfs_quota_us').write_text('50000')
            (root / 'cpu/cpu.cfs_period_us').write_text('100000')
            self.assertEqual(config.effective_cpus(root, root / 'missing'), 0.5)
            with patch.dict(os.environ, {'WEB_CPU_CORES': '0.1'}):
                self.assertEqual(config.effective_cpus(root, root / 'missing'), 0.1)

    def test_explicit_worker_override(self):
        with patch.dict(os.environ, {'WEB_WORKERS': '3'}):
            result = subprocess.run([sys.executable, '-c',
                'from sis_questionario.gunicorn_config import workers; print(workers)'],
                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), '3')

    @unittest.skipIf(sys.platform == 'win32', 'Gunicorn requires Unix.')
    def test_gevent_database_and_pool_waits_are_cooperative(self):
        if not os.environ.get('TEST_DATABASE_URL'):
            self.skipTest('Configure TEST_DATABASE_URL.')
        # Fresh interpreter: patch before importing Psycopg/pool, just as Gunicorn does.
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('gevent_pool_check.py'))],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
