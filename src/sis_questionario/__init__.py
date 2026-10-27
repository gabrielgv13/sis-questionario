def main() -> None:
    from .app import create_app

    create_app().run(host="127.0.0.1", port=5000)
