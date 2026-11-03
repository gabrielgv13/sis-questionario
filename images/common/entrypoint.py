"""Valida os segredos e inicia exclusivamente o processo web."""
import os

from sis_questionario.config import senha_banco

if not os.environ.get('SECRET_KEY') or len(os.environ['SECRET_KEY']) < 32:
    raise SystemExit('SECRET_KEY deve ter pelo menos 32 caracteres.')
if not (os.environ.get('ADMIN_PASSWORD') or os.environ.get('ADMIN_PASSWORD_HASH')):
    raise SystemExit('Configure ADMIN_PASSWORD ou ADMIN_PASSWORD_HASH.')
if os.environ.get('DB_USER') in (None, '', 'postgres', os.environ.get('DB_ADMIN_USER')):
    raise SystemExit('Configure DB_USER com uma conta restrita.')
if len(senha_banco()) < 24:
    raise SystemExit('Senha PostgreSQL ausente ou insuficiente.')
for key in tuple(os.environ):
    if key.startswith('DB_ADMIN_'):
        del os.environ[key]
os.execvp('gunicorn', ['gunicorn', 'sis_questionario.app:create_app()',
                      '--no-control-socket',
                      '--bind', '0.0.0.0:' + os.environ.get('PORT', '10000'),
                      '--workers', os.environ.get('WEB_WORKERS', '2'),
                      '--timeout', '60', '--access-logfile', '-', '--error-logfile', '-'])
