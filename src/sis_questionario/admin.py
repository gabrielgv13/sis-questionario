"""Authenticated, aggregate-only reporting interface."""
import json
import re
import secrets
from functools import wraps

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from .web import abort, redirect, render_template, read_json
from werkzeug.security import check_password_hash

from .bd_async import AsyncDatabase
from .bd_exec import QuestionarioExistente
from .async_pool import get_database

admin = APIRouter(prefix='/admin')


def protected(view):
    @wraps(view)
    async def wrapped(request: Request, *args, **kwargs):
        if not request.session.get('admin_authenticated'):
            if request.url.path.startswith('/admin/api/'):
                abort(401)
            return redirect(request, 'admin.login')
        return await view(request, *args, **kwargs)
    return wrapped


def csrf_token(request: Request):
    if 'admin_csrf' not in request.session:
        request.session['admin_csrf'] = secrets.token_urlsafe(32)
    return request.session['admin_csrf']


def check_csrf(request: Request, value):
    if not isinstance(value, str) or not value or not secrets.compare_digest(value, request.session.get('admin_csrf', '')):
        abort(400, description='Atualize a página e tente novamente.')


@admin.get('/login', name='admin.login')
@admin.head('/login', include_in_schema=False)
@admin.post('/login', name='admin.login_submit')
async def login(request: Request):
    password_hash = request.app.state.settings.get('ADMIN_PASSWORD_HASH')
    if not password_hash:
        return await render_template(request, 'admin_login.html', token=csrf_token(request),
                               error='Acesso administrativo ainda não configurado.', status_code=503)
    error = None
    if request.method == 'POST':
        form = await request.form()
        check_csrf(request, form.get('csrf_token'))
        password = form.get('password', '')
        if isinstance(password, str) and await run_in_threadpool(check_password_hash, password_hash, password):
            request.session.clear()
            request.session['admin_authenticated'] = True
            csrf_token(request)
            return redirect(request, 'admin.dashboard')
        error = 'Senha inválida.'
    return await render_template(request, 'admin_login.html', token=csrf_token(request), error=error)


@admin.post('/logout', name='admin.logout')
@protected
async def logout(request: Request):
    form = await request.form()
    check_csrf(request, form.get('csrf_token'))
    request.session.clear()
    return redirect(request, 'admin.login')


@admin.get('', name='admin.dashboard_alias')
@admin.head('', include_in_schema=False)
@admin.get('/', name='admin.dashboard')
@admin.head('/', include_in_schema=False)
@protected
async def dashboard(request: Request):
    return await render_template(request, 'admin_home.html', token=csrf_token(request))


@admin.get('/analise', name='admin.analysis')
@admin.head('/analise', include_in_schema=False)
@protected
async def analysis(request: Request, db: AsyncDatabase = Depends(get_database)):
    return await render_template(request, 'admin.html', questionarios=await db.listar_questionarios_admin(), token=csrf_token(request))


@admin.get('/questionarios', name='admin.questionnaires')
@admin.head('/questionarios', include_in_schema=False)
@protected
async def questionnaires(request: Request, db: AsyncDatabase = Depends(get_database)):
    return await render_template(request, 'admin_questionarios.html', questionarios=await db.listar_questionarios_admin(), token=csrf_token(request))


@admin.post('/api/questionnaires/import', name='admin.import_questionnaire')
@protected
async def import_questionnaire(request: Request, db: AsyncDatabase = Depends(get_database)):
    from .questionario_json import MAX_BYTES, ler_arquivo
    from .algoritmo_json import ler_arquivo as ler_algoritmo, regras_importacao
    check_csrf(request, request.headers.get('X-CSRF-Token'))
    # Bound the complete multipart body, including requests without Content-Length.
    limit = 2 * MAX_BYTES + 65536
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            abort(413)
    request._body = bytes(body)
    async with request.form(max_files=2, max_fields=10, max_part_size=limit) as form:
        upload = form.get('file')
        if not isinstance(upload, UploadFile) or not upload.filename or not upload.filename.lower().endswith('.json'):
            return JSONResponse({'error': 'Selecione um arquivo .json.'}, status_code=400)
        raw = await upload.read(MAX_BYTES + 1)
        algorithm = form.get('algorithm')
        algorithm_raw = None
        if algorithm is not None:
            if not isinstance(algorithm, UploadFile) or not algorithm.filename or not algorithm.filename.lower().endswith('.json'):
                return JSONResponse({'error': 'Selecione um arquivo .json para o algoritmo.'}, status_code=400)
            algorithm_raw = await algorithm.read(MAX_BYTES + 1)
        if len(form.getlist('file')) != 1 or len(form.getlist('algorithm')) > 1:
            return JSONResponse({'error': 'Envie apenas um questionário e um algoritmo.'}, status_code=400)
    try:
        documento = await run_in_threadpool(ler_arquivo, raw)
        regras = await run_in_threadpool(ler_algoritmo, algorithm_raw, documento) if algorithm_raw is not None else None
        regras = await run_in_threadpool(regras_importacao, documento, regras)
        identifier = await db.importar_questionario(documento, regras) if regras is not None else await db.importar_questionario(documento)
    except QuestionarioExistente as error:
        return JSONResponse({'error': str(error)}, status_code=409)
    except ValueError as error:
        return JSONResponse({'error': str(error)}, status_code=400)
    return JSONResponse({'id': identifier, 'title': documento['titulo']}, status_code=201)


@admin.get('/api/questionnaires/{identifier:int}/export', name='admin.export_questionnaire')
@admin.head('/api/questionnaires/{identifier:int}/export', include_in_schema=False)
@protected
async def export_questionnaire(request: Request, identifier: int, db: AsyncDatabase = Depends(get_database)):
    try:
        documento = await db.exportar_questionario(identifier)
    except ValueError as error:
        return JSONResponse({'error': str(error)}, status_code=400)
    if documento is None:
        abort(404)
    return Response(json.dumps(documento, ensure_ascii=False, indent=2),
                    media_type='application/json; charset=utf-8', headers={
                        'Content-Disposition': f'attachment; filename="questionario-{identifier}.json"'})


@admin.get('/api/questionnaires/{identifier:int}/algorithm', name='admin.export_algorithm')
@admin.head('/api/questionnaires/{identifier:int}/algorithm', include_in_schema=False)
@protected
async def export_algorithm(request: Request, identifier: int, db: AsyncDatabase = Depends(get_database)):
    try:
        regras = await db.exportar_algoritmo(identifier)
    except ValueError as error:
        return JSONResponse({'error': str(error)}, status_code=400)
    if regras is None:
        abort(404)
    filename = re.sub(r'[^a-zA-Z0-9_-]', '_', regras['version']) or f'algoritmo-{identifier}'
    return Response(json.dumps(regras, ensure_ascii=False, indent=2), media_type='application/json',
                    headers={'Content-Disposition': f'attachment; filename="{filename}.json"'})


@admin.post('/api/results', name='admin.results')
@protected
async def results(request: Request, db: AsyncDatabase = Depends(get_database)):
    check_csrf(request, request.headers.get('X-CSRF-Token'))
    data = await read_json(request)
    if not isinstance(data, dict) or type(data.get('quiz_id')) is not int:
        abort(400, description='Questionário inválido.')
    filters = data.get('filters', {})
    if not isinstance(filters, dict):
        abort(400, description='Filtros inválidos.')
    try:
        if 'profiles' in data:
            result = await db.resultados_questionario(data['quiz_id'], filters, data['profiles'])
        else:
            result = await db.resultados_questionario(data['quiz_id'], filters)
    except ValueError as error:
        abort(400, description=str(error))
    if result is None:
        abort(404)
    return JSONResponse(result)


@admin.post('/api/settings', name='admin.settings')
@protected
async def settings(request: Request, db: AsyncDatabase = Depends(get_database)):
    check_csrf(request, request.headers.get('X-CSRF-Token'))
    data = await read_json(request)
    if (not isinstance(data, dict) or type(data.get('quiz_id')) is not int
            or type(data.get('show_result')) is not bool):
        abort(400, description='Configuração inválida.')
    try:
        await db.configurar_devolutiva(data['quiz_id'], data['show_result'])
    except ValueError as error:
        abort(400, description=str(error))
    return JSONResponse({'ok': True})


@admin.post('/api/export', name='admin.export')
@protected
async def export(request: Request, db: AsyncDatabase = Depends(get_database)):
    from .exportacao import preparar_async, gerar_csv, gerar_json, gerar_pdf
    check_csrf(request, request.headers.get('X-CSRF-Token'))
    data = await read_json(request)
    try:
        result = await preparar_async(data, db)
    except ValueError as error:
        return JSONResponse({'error': str(error)}, status_code=400)
    kind = data['format']
    generators = {'pdf': (gerar_pdf, 'application/pdf'), 'csv': (gerar_csv, 'text/csv; charset=utf-8'),
                  'json': (gerar_json, 'application/json; charset=utf-8')}
    generate, content_type = generators[kind]
    return Response(await run_in_threadpool(generate, result), media_type=content_type, headers={
        'Content-Disposition': f'attachment; filename="questionario-{data["quiz_id"]}.{kind}"'})
