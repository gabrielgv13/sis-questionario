import os
from pathlib import Path

import psycopg
from psycopg import sql

from .config import carregar_configuracao


def main():
    """Prepara o banco usando Psycopg, sem precisar de psql."""
    carregar_configuracao()
    banco = os.environ.get('DB_NAME', 'mydatabase')
    conexao = dict(
        host=os.environ.get('DB_HOST', 'localhost'),
        port=int(os.environ.get('DB_PORT', '5432')),
        user=os.environ.get('DB_ADMIN_USER') or os.environ.get('DB_USER', 'postgres'),
        password=os.environ.get('DB_ADMIN_PASSWORD', os.environ.get('DB_PASSWORD', 'postgres')),
    )
    # CREATE DATABASE must run outside a transaction.
    with psycopg.connect(**conexao, dbname='postgres', autocommit=True) as conn:
        if not conn.execute('SELECT 1 FROM pg_database WHERE datname = %s', (banco,)).fetchone():
            conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(banco)))
    script = Path(__file__).with_name('banco.sql').read_text(encoding='utf-8')
    with psycopg.connect(**conexao, dbname=banco) as conn:
        conn.execute(script)
    print(f'Banco {banco} preparado.')
