"""Authenticated, aggregate-only reporting interface."""
import os
import json
import secrets
from functools import wraps

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for, Response
from werkzeug.security import check_password_hash

from . import bd_exec as db

admin = Blueprint('admin', __name__, url_prefix='/admin')


def protected(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('admin_authenticated'):
            if request.path.startswith('/admin/api/'):
                abort(401)
            return redirect(url_for('admin.login'))
        return view(*args, **kwargs)
    return wrapped


def csrf_token():
    if 'admin_csrf' not in session:
        session['admin_csrf'] = secrets.token_urlsafe(32)
    return session['admin_csrf']


def check_csrf(value):
    if not value or not secrets.compare_digest(value, session.get('admin_csrf', '')):
        abort(400, description='Atualize a página e tente novamente.')


@admin.route('/login', methods=['GET', 'POST'])
def login():
    password_hash = os.environ.get('ADMIN_PASSWORD_HASH')
    if not password_hash:
        return render_template('admin_login.html', token=csrf_token(),
                               error='Acesso administrativo ainda não configurado.'), 503
    error = None
    if request.method == 'POST':
        check_csrf(request.form.get('csrf_token'))
        if check_password_hash(password_hash, request.form.get('password', '')):
            session.clear()
            session['admin_authenticated'] = True
            csrf_token()
            return redirect(url_for('admin.dashboard'))
        error = 'Senha inválida.'
    return render_template('admin_login.html', token=csrf_token(), error=error)


@admin.post('/logout')
@protected
def logout():
    check_csrf(request.form.get('csrf_token'))
    session.clear()
    return redirect(url_for('admin.login'))


@admin.get('')
@admin.get('/')
@protected
def dashboard():
    return render_template('admin_home.html', token=csrf_token())


@admin.get('/analise')
@protected
def analysis():
    return render_template('admin.html', questionarios=db.listar_questionarios_admin(), token=csrf_token())


@admin.get('/questionarios')
@protected
def questionnaires():
    return render_template('admin_questionarios.html', questionarios=db.listar_questionarios_admin(), token=csrf_token())


@admin.post('/api/questionnaires/import')
@protected
def import_questionnaire():
    from .questionario_json import MAX_BYTES, ler_arquivo
    check_csrf(request.headers.get('X-CSRF-Token'))
    # Bound multipart parsing as well as the uploaded JSON itself.
    request.max_content_length = MAX_BYTES + 65536
    upload = request.files.get('file')
    if upload is None or not upload.filename or not upload.filename.lower().endswith('.json'):
        return jsonify(error='Selecione um arquivo .json.'), 400
    try:
        documento = ler_arquivo(upload.stream.read(MAX_BYTES + 1))
        identifier = db.importar_questionario(documento)
    except db.QuestionarioExistente as error:
        return jsonify(error=str(error)), 409
    except ValueError as error:
        return jsonify(error=str(error)), 400
    return jsonify(id=identifier, title=documento['titulo']), 201


@admin.get('/api/questionnaires/<int:identifier>/export')
@protected
def export_questionnaire(identifier):
    try:
        documento = db.exportar_questionario(identifier)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    if documento is None:
        abort(404)
    return Response(json.dumps(documento, ensure_ascii=False, indent=2),
                    content_type='application/json; charset=utf-8', headers={
                        'Content-Disposition': f'attachment; filename="questionario-{identifier}.json"'})


@admin.post('/api/results')
@protected
def results():
    check_csrf(request.headers.get('X-CSRF-Token'))
    data = request.get_json()
    if not isinstance(data, dict) or type(data.get('quiz_id')) is not int:
        abort(400, description='Questionário inválido.')
    filters = data.get('filters', {})
    if not isinstance(filters, dict):
        abort(400, description='Filtros inválidos.')
    try:
        if 'profiles' in data:
            result = db.resultados_questionario(data['quiz_id'], filters, data['profiles'])
        else:
            result = db.resultados_questionario(data['quiz_id'], filters)
    except ValueError as error:
        abort(400, description=str(error))
    if result is None:
        abort(404)
    return jsonify(result)


@admin.post('/api/settings')
@protected
def settings():
    check_csrf(request.headers.get('X-CSRF-Token'))
    data = request.get_json()
    if (not isinstance(data, dict) or type(data.get('quiz_id')) is not int
            or type(data.get('show_result')) is not bool):
        abort(400, description='Configuração inválida.')
    try:
        db.configurar_devolutiva(data['quiz_id'], data['show_result'])
    except ValueError as error:
        abort(400, description=str(error))
    return jsonify(ok=True)


@admin.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Frame-Options'] = 'DENY'
    return response


@admin.post('/api/export')
@protected
def export():
    from .exportacao import preparar, gerar_csv, gerar_json, gerar_pdf
    check_csrf(request.headers.get('X-CSRF-Token'))
    data = request.get_json()
    try:
        result = preparar(data)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    kind = data['format']
    generators = {'pdf': (gerar_pdf, 'application/pdf'), 'csv': (gerar_csv, 'text/csv; charset=utf-8'),
                  'json': (gerar_json, 'application/json; charset=utf-8')}
    generate, content_type = generators[kind]
    return Response(generate(result), content_type=content_type, headers={
        'Content-Disposition': f'attachment; filename="questionario-{data["quiz_id"]}.{kind}"'})
