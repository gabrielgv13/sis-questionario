def main() -> None:
    from .server import serve
    from .database_setup import main as prepare_database

    prepare_database()
    serve()


def main_perfil() -> None:
    from .server import serve
    from .sync_database import seed_profile_questionnaire
    from .database_setup import main as prepare_database

    prepare_database()
    seed_profile_questionnaire()
    serve()
