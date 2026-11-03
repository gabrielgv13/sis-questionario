import os
import secrets
from uuid import UUID, uuid4

from flask import Flask, abort, g, redirect, render_template, request, session, url_for

from . import bd_exec as db
from .config import carregar_configuracao


def create_app(inicializar=True):
    carregar_configuracao()
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY') or secrets.token_hex(32),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
    )
    if inicializar:
        db.inicializar_banco()

    from .admin import admin
    app.register_blueprint(admin)

    @app.errorhandler(400)
    def formulario_invalido(erro):
        return render_template('erro.html', erro=erro, titulo='Confira seu formulário',
                               descricao=erro.description), 400

    @app.errorhandler(404)
    def pagina_nao_encontrada(erro):
        return render_template('erro.html', erro=erro, titulo='Página não encontrada',
                               descricao='Este endereço não está disponível. Volte à página inicial para continuar.'), 404

    @app.before_request
    def identificar_navegador():
        cookie = request.cookies.get('id_dispositivo', '')
        try:
            identificador = UUID(cookie)
            if identificador.version != 4:
                raise ValueError('Identificador inválido.')
            g.id_dispositivo = str(identificador)
        except ValueError:
            g.id_dispositivo = str(uuid4())
            if request.method == 'POST':
                abort(400, description='Abra a página inicial e habilite os cookies antes de responder.')

    @app.after_request
    def salvar_identificador(response):
        if request.cookies.get('id_dispositivo') != g.id_dispositivo:
            response.set_cookie(
                'id_dispositivo', g.id_dispositivo, max_age=60 * 60 * 24 * 365,
                httponly=True, samesite='Lax', secure=request.is_secure,
            )
        return response

    @app.route('/')
    def index():
        return render_template('index.html', questionarios=db.listar_questionarios())

    @app.route('/submit-info', methods=['POST'])
    def submit():
        nome = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        questionario_id = request.form.get('questionario_id', type=int)
        if not nome or not email or '@' not in email:
            abort(400, description='Informe nome e e-mail válidos.')
        if not db.carregar_questionario(questionario_id):
            abort(400, description='Selecione um questionário disponível.')
        if db.dispositivo_ja_respondeu(g.id_dispositivo, questionario_id):
            return render_template('ja_respondido.html'), 409
        aluno_id = db.registrar_aluno(nome, email)
        session.clear()
        session['aluno_id'] = aluno_id
        session['questionario_id'] = questionario_id
        session['token_formulario'] = secrets.token_urlsafe(32)
        return redirect(url_for('pesquisa_perguntas'))

    @app.route('/pesquisa-perguntas')
    def pesquisa_perguntas():
        if not session.get('aluno_id') or not session.get('questionario_id'):
            return redirect(url_for('index'))
        if db.dispositivo_ja_respondeu(g.id_dispositivo, session['questionario_id']):
            return render_template('ja_respondido.html'), 409
        questionario = db.carregar_questionario(session['questionario_id'])
        if not questionario:
            return redirect(url_for('index'))
        return render_template('perguntas.html', questionario=questionario,
                               perguntas=questionario['perguntas'])

    @app.route('/submit-pesquisa', methods=['POST'])
    def submit_pesquisa():
        if not session.get('aluno_id') or not session.get('questionario_id'):
            return redirect(url_for('index'))
        token = request.form.get('token_formulario', '')
        if not token or not secrets.compare_digest(token, session.get('token_formulario', '')):
            abort(400, description='Formulário inválido. Abra o questionário novamente.')
        respostas = {}
        try:
            for campo in request.form:
                if campo.startswith('pergunta_'):
                    valores = request.form.getlist(campo)
                    if len(valores) != 1:
                        raise ValueError('Selecione apenas uma opção por pergunta.')
                    respostas[int(campo.removeprefix('pergunta_'))] = int(valores[0])
            id_envio = db.registrar_envio(session['aluno_id'], session['questionario_id'], respostas,
                               g.id_dispositivo)
        except db.EnvioDuplicado:
            return render_template('ja_respondido.html'), 409
        except ValueError as erro:
            abort(400, description=str(erro))
        session.pop('questionario_id', None)
        session.pop('token_formulario', None)
        session['envio_concluido'] = True
        session['envio_id'] = id_envio
        return redirect(url_for('concluido'))

    @app.route('/concluido')
    def concluido():
        if not session.get('envio_concluido'):
            return redirect(url_for('index'))
        from .perfis import PERFIS
        resultado = db.carregar_resultado(session['envio_id'], g.id_dispositivo) if session.get('envio_id') else None
        response = app.make_response(render_template('concluido.html', resultado=resultado, perfis=PERFIS))
        response.headers['Cache-Control'] = 'no-store'
        return response

    return app
