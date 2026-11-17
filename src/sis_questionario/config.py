from pathlib import Path
import os

from dotenv import load_dotenv


def carregar_configuracao():
    # A configuração do ambiente de hospedagem tem prioridade sobre o arquivo local.
    load_dotenv(Path.cwd() / '.env', override=False)


def senha_banco():
    arquivo = os.environ.get('DB_PASSWORD_FILE')
    return Path(arquivo).read_text(encoding='utf-8').strip() if arquivo else os.environ.get('DB_PASSWORD', 'postgres')


def conexao_banco():
    return dict(host=os.environ.get('DB_HOST', 'localhost'),
                port=int(os.environ.get('DB_PORT', '5432')),
                dbname=os.environ.get('DB_NAME', 'mydatabase'),
                user=os.environ.get('DB_USER', 'postgres'), password=senha_banco(),
                sslmode=os.environ.get('DB_SSLMODE', 'prefer'), connect_timeout=5)
