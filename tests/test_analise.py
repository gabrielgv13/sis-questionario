import copy
import time
import unittest
from datetime import datetime
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from werkzeug.security import generate_password_hash

from sis_questionario.app import create_app


class AnaliseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.senha_hash = generate_password_hash('senha-de-teste')

    def setUp(self):
        self.app = create_app(inicializar=False)
        self.app.config.update(TESTING=True, ADMIN_PASSWORD_HASH=self.senha_hash)
        self.client = self.app.test_client()
        self.questionario = {'id_questionario': 1, 'codigo': 'perfil', 'titulo': 'Perfil',
            'ativo': True, 'perguntas': [
                {'id_pergunta': 1, 'ordem': 1, 'enunciado': 'Matéria?', 'opcoes': [
                    {'id_opcao': 1, 'texto': 'Artes', 'total': 1, 'percentual': 100}]},
                {'id_pergunta': 2, 'ordem': 4, 'enunciado': 'Música?', 'opcoes': [
                    {'id_opcao': 2, 'texto': 'Rock', 'total': 1, 'percentual': 100},
                    {'id_opcao': 3, 'texto': '<script>Metal</script>', 'total': 0, 'percentual': 0}]},
                {'id_pergunta': 3, 'ordem': 11, 'enunciado': 'Jogo?', 'opcoes': [
                    {'id_opcao': 4, 'texto': 'FIFA 20', 'total': 1, 'percentual': 100},
                    {'id_opcao': 5, 'texto': 'The King Of Fighters', 'total': 0, 'percentual': 0}]}]}
        self.dados = {'questionario': self.questionario, 'selecionados': 1, 'total': 2,
            'pagina': 1, 'paginas': 2, 'envios': [
                {'id_envio': 1, 'data_envio': datetime(2026, 10, 30, 10),
                 'respostas': {'1': 'Artes', '2': 'Rock', '3': 'FIFA 20'}}]}

    def login(self, senha='senha-de-teste'):
        self.client.get('/admin/login')
        with self.client.session_transaction() as sessao:
            token = sessao['token_admin']
        return self.client.post('/admin/login', data={'senha': senha, 'token_admin': token})

    def test_acesso_anonimo_nao_consulta_dados(self):
        with patch('sis_questionario.app.db.listar_questionarios_analise') as listar:
            resposta = self.client.get('/analise?opcao=2')
        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(resposta.location.endswith('/admin/login'))
        self.assertEqual(resposta.headers['Cache-Control'], 'no-store')
        listar.assert_not_called()

    def test_login_logout_csrf_expiracao_e_troca_de_senha(self):
        self.client.get('/admin/login')
        for token in ('', 'inválido'):
            self.assertEqual(self.client.post('/admin/login', data={
                'senha': 'senha-de-teste', 'token_admin': token}).status_code, 400)
        self.assertEqual(self.login('errada').status_code, 401)
        self.assertEqual(self.login().status_code, 302)
        with self.client.session_transaction() as sessao:
            token = sessao['token_admin']
        self.assertEqual(self.client.post('/admin/logout').status_code, 400)
        self.assertEqual(self.client.post('/admin/logout', data={'token_admin': token}).status_code, 302)
        self.assertTrue(self.client.get('/analise').location.endswith('/admin/login'))
        self.login()
        with self.client.session_transaction() as sessao:
            sessao['admin_expira'] = time.time() - 1
        self.assertTrue(self.client.get('/analise').location.endswith('/admin/login'))
        self.login()
        self.app.config['ADMIN_PASSWORD_HASH'] = generate_password_hash('outra-senha')
        self.assertTrue(self.client.get('/analise').location.endswith('/admin/login'))

    def test_sem_senha_configurada_e_limite_de_tentativas(self):
        self.app.config['ADMIN_PASSWORD_HASH'] = ''
        self.assertEqual(self.client.get('/admin/login').status_code, 503)
        self.app.config['ADMIN_PASSWORD_HASH'] = self.senha_hash
        for _ in range(5):
            self.assertEqual(self.login('errada').status_code, 401)
        self.assertEqual(self.login().status_code, 429)

    def test_filtros_links_tabela_e_escape_html(self):
        self.login()
        with patch('sis_questionario.app.db.listar_questionarios_analise', return_value=[self.questionario]), \
                patch('sis_questionario.app.db.carregar_analise', return_value=self.dados) as carregar:
            resposta = self.client.get('/analise?questionario=1&opcao=2&opcao=4')
        carregar.assert_called_once_with(1, [2, 4], 1)
        self.assertEqual(resposta.status_code, 200)
        html = resposta.get_data(as_text=True)
        self.assertIn('1 <span', html)
        self.assertIn('de 2 envios', html)
        self.assertIn('100,0%', html)
        self.assertIn('30/10/2026 10:00', html)
        self.assertNotIn('<script>Metal</script>', html)
        self.assertIn('&lt;script&gt;Metal&lt;/script&gt;', html)
        self.assertNotIn('email', html)
        from html.parser import HTMLParser

        class Links(HTMLParser):
            def __init__(self):
                super().__init__()
                self.links = []

            def handle_starttag(self, tag, attrs):
                if tag == 'a':
                    self.links.append(dict(attrs).get('href', ''))

        parser = Links()
        parser.feed(html)
        consultas = [parse_qs(urlsplit(link).query) for link in parser.links
                     if urlsplit(link).path == '/analise']
        self.assertIn({'questionario': ['1'], 'opcao': ['4', '3'], 'pagina': ['1']}, consultas)
        self.assertIn({'questionario': ['1'], 'opcao': ['4'], 'pagina': ['1']}, consultas)
        self.assertIn({'questionario': ['1'], 'pagina': ['1']}, consultas)
        self.assertIn({'questionario': ['1'], 'opcao': ['2', '4'], 'pagina': ['2']}, consultas)

    def test_filtros_invalidos_e_estados_vazios(self):
        self.login()
        with patch('sis_questionario.app.db.listar_questionarios_analise', return_value=[self.questionario]):
            for consulta in ('opcao=x', 'pagina=x', 'questionario=x', 'questionario=99999999999999999999'):
                self.assertEqual(self.client.get('/analise?' + consulta).status_code, 400)
            with patch('sis_questionario.app.db.carregar_analise', side_effect=ValueError('Filtro inválido')):
                self.assertEqual(self.client.get('/analise?opcao=-1').status_code, 400)
            with patch('sis_questionario.app.db.carregar_analise', return_value=None):
                self.assertEqual(self.client.get('/analise?questionario=42').status_code, 404)
            vazio = copy.deepcopy(self.dados)
            vazio.update(selecionados=0, envios=[])
            with patch('sis_questionario.app.db.carregar_analise', return_value=vazio):
                resposta = self.client.get('/analise?opcao=2&opcao=4')
                self.assertIn('Nenhum envio corresponde', resposta.get_data(as_text=True))
        with patch('sis_questionario.app.db.listar_questionarios_analise', return_value=[]):
            resposta = self.client.get('/analise')
            self.assertEqual(resposta.status_code, 200)
            self.assertIn('Nenhum questionário cadastrado', resposta.get_data(as_text=True))
