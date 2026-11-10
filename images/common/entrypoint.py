"""Valida os segredos e inicia exclusivamente o processo web."""
import os
import sys

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
os.environ.setdefault('WEB_HOST', '0.0.0.0')
os.environ.setdefault('PORT', '10000')
if os.environ.get('WEB_RELOAD', '0') != '0':
    raise SystemExit('WEB_RELOAD deve ser 0 nos containers.')
os.execvp(sys.executable, [sys.executable, '-m', 'sis_questionario.server'])
