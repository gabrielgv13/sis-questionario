import os
from pathlib import Path
import shutil
import subprocess

from .config import carregar_configuracao


def main():
    """Executa o SQL único com o administrador; o app usa somente client-app."""
    carregar_configuracao()
    if not os.environ.get('DB_PASSWORD'):
        raise SystemExit('Preencha DB_PASSWORD no .env antes de preparar o banco.')
    psql = os.environ.get('PSQL_PATH') or shutil.which('psql')
    if not psql:
        raise SystemExit('Informe PSQL_PATH no .env ou adicione o psql ao PATH.')
    script = Path(__file__).with_name('banco.sql')
    result = subprocess.run([
        psql, '-X', '-h', os.environ.get('DB_HOST', 'localhost'),
        '-p', os.environ.get('DB_PORT', '5432'),
        '-U', os.environ.get('DB_ADMIN_USER', 'postgres'),
        '-d', 'postgres', '-f', str(script),
    ], check=False)
    raise SystemExit(result.returncode)
