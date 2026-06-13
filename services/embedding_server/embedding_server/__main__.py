import logging

from aiohttp import web

from embedding_server.app import create_app
from embedding_server.config import ServerSettings


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = ServerSettings.from_env()
    web.run_app(
        create_app(settings=settings),
        host=settings.host,
        port=settings.port,
        access_log_format='%a "%r" %s %b %Tf',
    )


if __name__ == "__main__":
    main()
