import hashlib
import os
import secrets
import time
from uuid import UUID, uuid4

from flask import Flask, abort, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from . import bd_exec as db
from .config import carregar_configuracao


def create_app(inicializar=True):
    carregar_configuracao()
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY') or secrets.token_hex(32),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE', '').lower() == 'true',
        ADMIN_PASSWORD_HASH=os.environ.get('ADMIN_PASSWORD_HASH', ''),
    )
    if inicializar:
        db.inicializar_banco()

    tentativas_login = {}

    def admin_autenticado():
        senha_hash = app.config['ADMIN_PASSWORD_HASH']
        return bool(senha_hash and session.get('admin_expira', 0) > time.time()
                    and secrets.compare_digest(session.get('admin_credencial', ''),
                        hashlib.sha256(senha_hash.encode()).hexdigest()))

    def validar_token_admin():
        token = request.form.get('token_admin', '')
        if not token or not secrets.compare_digest(token.encode(), session.get('token_admin', '').encode()):
            abort(400, description='Formulário expirado. Abra a página novamente.')

    @app.route('/admin/login', methods=['GET', 'POST'])
    def admin_login():
        if not app.config['ADMIN_PASSWORD_HASH']:
            return render_template('admin_login.html', indisponivel=True), 503
        if admin_autenticado():
            return redirect(url_for('analise'))
        erro = None
        status = 200
        session.setdefault('token_admin', secrets.token_urlsafe(32))
        if request.method == 'POST':
            validar_token_admin()
            agora = time.time()
            for endereco, (_, fim) in list(tentativas_login.items()):
                if fim <= agora:
                    del tentativas_login[endereco]
            endereco = request.remote_addr
            quantidade, fim = tentativas_login.get(endereco, (0, agora + 300))
            if quantidade >= 5:
                erro, status = 'Muitas tentativas. Aguarde cinco minutos para tentar novamente.', 429
            else:
                senha = request.form.get('senha', '')
                try:
                    valida = len(senha) <= 1024 and check_password_hash(app.config['ADMIN_PASSWORD_HASH'], senha)
                except ValueError:
                    valida = False
                if valida:
                    tentativas_login.pop(endereco, None)
                    session.clear()
                    session['admin_expira'] = agora + 3600
                    session['admin_credencial'] = hashlib.sha256(app.config['ADMIN_PASSWORD_HASH'].encode()).hexdigest()
                    session['token_admin'] = secrets.token_urlsafe(32)
                    return redirect(url_for('analise'))
                tentativas_login[endereco] = (quantidade + 1, fim)
                erro, status = 'Senha incorreta.', 401
        return render_template('admin_login.html', erro=erro), status

    @app.route('/admin/logout', methods=['POST'])
    def admin_logout():
        if not admin_autenticado():
            return redirect(url_for('admin_login'))
        validar_token_admin()
        session.clear()
        return redirect(url_for('admin_login'))

    @app.route('/analise')
    def analise():
        if not admin_autenticado():
            return redirect(url_for('admin_login'))
        questionarios = db.listar_questionarios_analise()
        try:
            questionario_id = int(request.args.get('questionario', questionarios[0]['id_questionario']
                                                 if questionarios else 0))
            filtros = [int(o) for o in request.args.getlist('opcao') if o != '']
            pagina = int(request.args.get('pagina', '1'))
            if questionario_id < 0 or questionario_id > 2147483647:
                raise ValueError('Questionário inválido.')
        except ValueError:
            abort(400, description='Filtros de análise inválidos.')
        try:
            dados = db.carregar_analise(questionario_id, filtros, pagina) if questionario_id else None
        except ValueError as erro:
            abort(400, description=str(erro))
        if questionario_id and dados is None:
            abort(404)
        perguntas = dados['questionario']['perguntas'] if dados else []

        def link_filtro(opcao=None, limpar=False, pagina=1):
            novos = [] if limpar else list(filtros)
            if opcao is not None:
                pergunta = next(p for p in perguntas if any(o['id_opcao'] == opcao for o in p['opcoes']))
                novos = [o for o in novos if o not in {v['id_opcao'] for v in pergunta['opcoes']}]
                if opcao not in filtros:
                    novos.append(opcao)
            return url_for('analise', questionario=questionario_id, opcao=novos, pagina=pagina)

        jogo = next((p for p in perguntas if dados['questionario']['codigo'] == 'perfil' and p['ordem'] == 11), None)
        selecionados = [(p, o) for p in perguntas for o in p['opcoes'] if o['id_opcao'] in filtros]
        return render_template('analise.html', dados=dados, questionarios=questionarios,
                               filtros=filtros, selecionados=selecionados, jogo=jogo,
                               link_filtro=link_filtro)

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
        if request.endpoint in {'analise', 'admin_login', 'admin_logout'}:
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
            response.headers['Referrer-Policy'] = 'same-origin'
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
            db.registrar_envio(session['aluno_id'], session['questionario_id'], respostas,
                               g.id_dispositivo)
        except db.EnvioDuplicado:
            return render_template('ja_respondido.html'), 409
        except ValueError as erro:
            abort(400, description=str(erro))
        session.pop('questionario_id', None)
        session.pop('token_formulario', None)
        session['envio_concluido'] = True
        return redirect(url_for('concluido'))

    @app.route('/concluido')
    def concluido():
        if not session.get('envio_concluido'):
            return redirect(url_for('index'))
        return render_template('concluido.html')

    return app
