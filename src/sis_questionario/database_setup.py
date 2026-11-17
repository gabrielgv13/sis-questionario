import os
from pathlib import Path

import psycopg
from psycopg import sql

from .config import carregar_configuracao


def main():
    """Prepara o banco usando Psycopg, sem precisar de psql."""
    carregar_configuracao()
    database_name = os.environ.get('DB_NAME', 'mydatabase')
    connection_options = dict(
        host=os.environ.get('DB_HOST', 'localhost'),
        port=int(os.environ.get('DB_PORT', '5432')),
        user=os.environ.get('DB_ADMIN_USER') or os.environ.get('DB_USER', 'postgres'),
        password=os.environ.get('DB_ADMIN_PASSWORD', os.environ.get('DB_PASSWORD', 'postgres')),
        sslmode=os.environ.get('DB_SSLMODE', 'prefer'),
        connect_timeout=5,
    )
    # CREATE DATABASE must run outside a transaction.
    with psycopg.connect(**connection_options, dbname='postgres', autocommit=True) as conn:
        if not conn.execute('SELECT 1 FROM pg_database WHERE datname = %s', (database_name,)).fetchone():
            conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database_name)))
    script = Path(__file__).with_name('banco.sql').read_text(encoding='utf-8')
    with psycopg.connect(**connection_options, dbname=database_name) as conn:
        conn.execute(script)
    print(f'Banco {database_name} preparado.')
