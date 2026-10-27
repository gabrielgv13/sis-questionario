from pathlib import Path

from dotenv import load_dotenv


def carregar_configuracao():
    # A configuração do ambiente de hospedagem tem prioridade sobre o arquivo local.
    load_dotenv(Path.cwd() / '.env', override=False)
