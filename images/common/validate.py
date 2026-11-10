"""Execute integration tests with an escaped DSN, including special passwords."""
import os
import sys

from psycopg.conninfo import make_conninfo

os.environ['TEST_DATABASE_URL'] = make_conninfo(
    host=os.environ['DB_HOST'], port=os.environ.get('DB_PORT', '5432'),
    dbname=os.environ['DB_NAME'], user=os.environ['DB_ADMIN_USER'],
    password=os.environ['DB_ADMIN_PASSWORD'], sslmode=os.environ.get('DB_SSLMODE', 'prefer'),
    connect_timeout=5,
)
os.execvp(sys.executable, [sys.executable, '-m', 'unittest', 'discover', '-s', '/app/tests', '-v'])
