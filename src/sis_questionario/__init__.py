def main() -> None:
    from .app import create_app

    create_app().run(host="127.0.0.1", port=5000)


def main_perfil() -> None:
    from .app import create_app
    from .bd_exec import inicializar_banco

    inicializar_banco()
    create_app().run(host="127.0.0.1", port=5000)
