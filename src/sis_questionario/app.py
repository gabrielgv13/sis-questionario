import os
import secrets
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg_pool import PoolClosed, PoolTimeout, TooManyRequests
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles
from werkzeug.security import generate_password_hash

from .async_database import AsyncDatabase
from .async_pool import get_database, lifespan
from .config import carregar_configuracao
from .participant_routes import router as participant_router
from .web import render_template


def create_app(inicializar=False):
    carregar_configuracao()
    app = FastAPI(title='Sistema de questionários', lifespan=lifespan)
    app.state.database = AsyncDatabase(None)
    app.state.settings = {
        'SECRET_KEY': os.environ.get('SECRET_KEY') or secrets.token_hex(32),
        'SESSION_COOKIE_SECURE': os.environ.get('COOKIE_SECURE') == '1',
        'ADMIN_PASSWORD_HASH': os.environ.get('ADMIN_PASSWORD_HASH') or (
            generate_password_hash(os.environ['ADMIN_PASSWORD']) if os.environ.get('ADMIN_PASSWORD') else None),
    }
    app.add_middleware(
        SessionMiddleware, secret_key=app.state.settings['SECRET_KEY'],
        session_cookie='session', max_age=None, same_site='lax',
        https_only=app.state.settings['SESSION_COOKIE_SECURE'],
    )
    if inicializar:
        from .sync_database import seed_profile_questionnaire
        seed_profile_questionnaire()

    from .admin import admin
    app.include_router(admin)
    app.include_router(participant_router)
    app.mount('/static', StaticFiles(directory=Path(__file__).with_name('static')), name='static')

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        if error.status_code in (400, 404):
            return await render_template(
                request, 'error.html', status_code=error.status_code, erro=error,
                titulo='Confira seu formulário' if error.status_code == 400 else 'Página não encontrada',
                descricao=error.detail if error.status_code == 400 else
                'Este endereço não está disponível. Volte à página inicial para continuar.',
            )
        return JSONResponse({'detail': error.detail}, status_code=error.status_code, headers=error.headers)

    async def database_unavailable(request: Request, error):
        return JSONResponse({'status': 'unavailable'}, status_code=503)

    for error_type in (psycopg.OperationalError, PoolTimeout, TooManyRequests, PoolClosed):
        app.add_exception_handler(error_type, database_unavailable)

    @app.middleware('http')
    async def browser_and_privacy(request: Request, call_next):
        cookie = request.cookies.get('id_dispositivo', '')
        try:
            identifier = UUID(cookie)
            if identifier.version != 4:
                raise ValueError('Identificador inválido.')
            request.state.id_dispositivo = str(identifier)
            invalid = False
        except ValueError:
            request.state.id_dispositivo = str(uuid4())
            invalid = True
        if invalid and request.method == 'POST':
            response = await http_error(request, HTTPException(
                400, 'Abra a página inicial e habilite os cookies antes de responder.'))
        else:
            response = await call_next(request)
        if cookie != request.state.id_dispositivo:
            response.set_cookie(
                'id_dispositivo', request.state.id_dispositivo, max_age=60 * 60 * 24 * 365,
                httponly=True, samesite='lax',
                secure=app.state.settings['SESSION_COOKIE_SECURE'] or request.url.scheme == 'https',
            )
        if request.url.path == '/admin' or request.url.path.startswith('/admin/'):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Frame-Options'] = 'DENY'
        return response

    @app.get('/healthz')
    @app.head('/healthz', include_in_schema=False)
    async def health(request: Request, db: AsyncDatabase = Depends(get_database)):
        try:
            await db.check_health()
            return {'status': 'ok'}
        except (psycopg.Error, PoolTimeout, TooManyRequests, PoolClosed):
            return JSONResponse({'status': 'unavailable'}, status_code=503)

    return app
