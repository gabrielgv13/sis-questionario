def main() -> None:
    from .server import serve
    from .setup_db import main as preparar_banco

    preparar_banco()
    serve()


def main_perfil() -> None:
    from .server import serve
    from .bd_exec import inicializar_banco
    from .setup_db import main as preparar_banco

    preparar_banco()
    inicializar_banco()
    serve()
