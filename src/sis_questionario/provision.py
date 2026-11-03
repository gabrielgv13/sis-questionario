"""Provisionamento de um banco dedicado; nunca executado pela factory web."""
import os
import re
import secrets
import time
from pathlib import Path

import psycopg
from psycopg import sql

from .config import carregar_configuracao, conexao_banco

TABLES = ('alunos', 'questionarios', 'perguntas', 'opcoes', 'envios', 'respostas')


def preparar_senha():
    arquivo = os.environ.get('DB_PASSWORD_FILE')
    if arquivo:
        path = Path(arquivo)
        if not path.exists():
            # O volume deve pertencer ao mesmo UID do provisionador e do web.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(secrets.token_urlsafe(48))
        senha = path.read_text(encoding='utf-8').strip()
    else:
        senha = os.environ.get('DB_PASSWORD', '')
    if len(senha) < 24:
        raise ValueError('Configure uma senha de aplicação com pelo menos 24 caracteres.')
    return senha


def provisionar():
    carregar_configuracao()
    usuario = os.environ.get('DB_USER', 'sis_app')
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', usuario):
        raise ValueError('DB_USER deve ser um identificador simples de até 63 caracteres.')
    if not os.environ.get('DB_ADMIN_USER') or not os.environ.get('DB_ADMIN_PASSWORD'):
        raise ValueError('Credenciais administrativas são obrigatórias no provisionamento.')
    if usuario == os.environ['DB_ADMIN_USER']:
        raise ValueError('A conta da aplicação deve ser diferente da conta administrativa.')
    # Não ler DB_PASSWORD_FILE antes que o provisionador o tenha criado.
    admin_options = dict(host=os.environ.get('DB_HOST', 'localhost'),
                         port=int(os.environ.get('DB_PORT', '5432')),
                         dbname=os.environ.get('DB_NAME', 'sis_questionario'),
                         user=os.environ['DB_ADMIN_USER'], password=os.environ['DB_ADMIN_PASSWORD'],
                         sslmode=os.environ.get('DB_SSLMODE', 'prefer'), connect_timeout=5)
    for tentativa in range(12):
        try:
            conn = psycopg.connect(**admin_options, autocommit=True)
            break
        except psycopg.OperationalError:
            if tentativa == 11:
                raise RuntimeError('Não foi possível conectar ao banco para provisionamento.') from None
            time.sleep(2)
    with conn:
        # Lock de sessão mantido inclusive durante a carga idempotente.
        conn.execute("SET lock_timeout = '30s'")
        conn.execute('SELECT pg_advisory_lock(734190261)')
        try:
            senha = preparar_senha()
            app_options = {**conexao_banco(), 'user': usuario, 'password': senha}
            with conn.transaction():
                existing = conn.execute('SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, '
                                        'rolbypassrls FROM pg_roles WHERE rolname = %s', (usuario,)).fetchone()
                role = sql.Identifier(usuario)
                if existing:
                    membership = conn.execute('SELECT 1 FROM pg_auth_members m JOIN pg_roles r '
                                              'ON r.oid=m.member WHERE r.rolname=%s', (usuario,)).fetchone()
                    ownership = conn.execute('SELECT 1 FROM pg_class c JOIN pg_roles r '
                                            'ON r.oid=c.relowner WHERE r.rolname=%s LIMIT 1', (usuario,)).fetchone()
                    if any(existing) or membership or ownership:
                        raise ValueError('A role existente possui privilégios incompatíveis; use uma role nova.')
                    try:
                        with psycopg.connect(**app_options):
                            pass
                    except psycopg.Error:
                        raise ValueError('A senha da role existente não corresponde à configuração.') from None
                else:
                    conn.execute(sql.SQL('CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB '
                                         'NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}')
                                 .format(role, sql.Literal(senha)))
                conn.execute(Path(__file__).with_name('banco.sql').read_text(encoding='utf-8'))
                conn.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
                conn.execute(sql.SQL('REVOKE CREATE ON SCHEMA public FROM {}').format(role))
                conn.execute(sql.SQL('REVOKE CREATE ON DATABASE {} FROM {}')
                             .format(sql.Identifier(app_options['dbname']), role))
                conn.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}')
                             .format(sql.Identifier(app_options['dbname']), role))
                conn.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(role))
                tables = sql.SQL(', ').join(sql.Identifier('public', table) for table in TABLES)
                conn.execute(sql.SQL('REVOKE ALL ON {} FROM {}').format(tables, role))
                conn.execute(sql.SQL('GRANT SELECT, INSERT ON {} TO {}').format(tables, role))
                conn.execute(sql.SQL('GRANT UPDATE (exibir_resultado, documento) ON public.questionarios TO {}').format(role))
                for table in TABLES:
                    sequence = conn.execute('SELECT pg_get_serial_sequence(%s, %s)',
                                            ('public.' + table, 'id_' + {
                                                'alunos': 'aluno', 'questionarios': 'questionario',
                                                'perguntas': 'pergunta', 'opcoes': 'opcao',
                                                'envios': 'envio', 'respostas': 'resposta'}[table])).fetchone()[0]
                    conn.execute(sql.SQL('GRANT USAGE ON SEQUENCE {} TO {}')
                                 .format(sql.Identifier(*sequence.split('.')), role))
            if os.environ.get('SEED_PROFILE', '0') == '1':
                from .bd_exec import inicializar_banco
                inicializar_banco()
        finally:
            conn.execute('SELECT pg_advisory_unlock(734190261)')


def main():
    try:
        provisionar()
    except (psycopg.Error, OSError):
        raise SystemExit('Falha no provisionamento. Verifique conexão, CREATEROLE e propriedade dos objetos.') from None
    print('Banco preparado; credenciais preservadas.')


if __name__ == '__main__':
    main()
