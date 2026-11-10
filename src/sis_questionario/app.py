import os
import secrets
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles
from werkzeug.security import generate_password_hash

from .bd_async import AsyncDatabase
from .bd_exec import EnvioDuplicado
from .async_pool import get_database, lifespan
from psycopg_pool import PoolTimeout, TooManyRequests, PoolClosed
from .config import carregar_configuracao
from .web import abort, redirect, render_template


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
        from .bd_exec import inicializar_banco
        inicializar_banco()

    from .admin import admin
    app.include_router(admin)
    app.mount('/static', StaticFiles(directory=Path(__file__).with_name('static')), name='static')

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        if error.status_code in (400, 404):
            return await render_template(
                request, 'erro.html', status_code=error.status_code, erro=error,
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

    @app.get('/')
    @app.head('/', include_in_schema=False)
    async def index(request: Request, db: AsyncDatabase = Depends(get_database)):
        return await render_template(request, 'index.html', questionarios=await db.listar_questionarios())

    @app.get('/healthz')
    @app.head('/healthz', include_in_schema=False)
    async def health(request: Request, db: AsyncDatabase = Depends(get_database)):
        try:
            await db.check_health()
            return {'status': 'ok'}
        except (psycopg.Error, PoolTimeout, TooManyRequests, PoolClosed):
            return JSONResponse({'status': 'unavailable'}, status_code=503)

    @app.post('/submit-info')
    async def submit(request: Request, db: AsyncDatabase = Depends(get_database)):
        form = await request.form()
        nome = form.get('name', '').title()
        email = form.get('email', '')
        if not isinstance(nome, str) or not isinstance(email, str):
            abort(400, description='Informe nome e e-mail válidos.')
        nome = nome.strip()
        email = email.strip().lower()
        try:
            questionario_id = int(form.get('questionario_id', ''))
        except (ValueError, TypeError):
            questionario_id = None
        if not nome or not email or '@' not in email:
            abort(400, description='Informe nome e e-mail válidos.')
        if not await db.carregar_questionario(questionario_id):
            abort(400, description='Selecione um questionário disponível.')
        if await db.dispositivo_ja_respondeu(request.state.id_dispositivo, questionario_id):
            return await render_template(request, 'ja_respondido.html', status_code=409)
        aluno_id = await db.registrar_aluno(nome, email)
        request.session.clear()
        request.session['aluno_id'] = aluno_id
        request.session['questionario_id'] = questionario_id
        request.session['token_formulario'] = secrets.token_urlsafe(32)
        return redirect(request, 'pesquisa_perguntas')

    @app.get('/pesquisa-perguntas')
    @app.head('/pesquisa-perguntas', include_in_schema=False)
    async def pesquisa_perguntas(request: Request, db: AsyncDatabase = Depends(get_database)):
        if not request.session.get('aluno_id') or not request.session.get('questionario_id'):
            return redirect(request, 'index')
        if await db.dispositivo_ja_respondeu(request.state.id_dispositivo, request.session['questionario_id']):
            return await render_template(request, 'ja_respondido.html', status_code=409)
        questionario = await db.carregar_questionario(request.session['questionario_id'])
        if not questionario:
            return redirect(request, 'index')
        return await render_template(request, 'perguntas.html', questionario=questionario,
                               perguntas=questionario['perguntas'])

    @app.post('/submit-pesquisa')
    async def submit_pesquisa(request: Request, db: AsyncDatabase = Depends(get_database)):
        if not request.session.get('aluno_id') or not request.session.get('questionario_id'):
            return redirect(request, 'index')
        form = await request.form()
        token = form.get('token_formulario', '')
        if not isinstance(token, str) or not token or not secrets.compare_digest(token, request.session.get('token_formulario', '')):
            abort(400, description='Formulário inválido. Abra o questionário novamente.')
        respostas = {}
        try:
            for campo in form:
                if campo.startswith('pergunta_'):
                    valores = form.getlist(campo)
                    if len(valores) != 1:
                        raise ValueError('Selecione apenas uma opção por pergunta.')
                    respostas[int(campo.removeprefix('pergunta_'))] = int(valores[0])
            id_envio = await db.registrar_envio(request.session['aluno_id'], request.session['questionario_id'], respostas,
                               request.state.id_dispositivo)
        except EnvioDuplicado:
            return await render_template(request, 'ja_respondido.html', status_code=409)
        except (ValueError, TypeError) as erro:
            abort(400, description=str(erro))
        request.session.pop('questionario_id', None)
        request.session.pop('token_formulario', None)
        request.session['envio_concluido'] = True
        request.session['envio_id'] = id_envio
        return redirect(request, 'concluido')

    @app.get('/concluido')
    @app.head('/concluido', include_in_schema=False)
    async def concluido(request: Request, db: AsyncDatabase = Depends(get_database)):
        if not request.session.get('envio_concluido'):
            return redirect(request, 'index')
        from .perfis import PERFIS
        resultado = await db.carregar_resultado(request.session['envio_id'], request.state.id_dispositivo) if request.session.get('envio_id') else None
        response = await render_template(request, 'concluido.html', resultado=resultado,
                                         perfis=resultado.get('profiles', PERFIS) if resultado else PERFIS)
        response.headers['Cache-Control'] = 'no-store'
        return response

    return app
