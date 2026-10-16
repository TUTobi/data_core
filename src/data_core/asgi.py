"""ASGI entrypoint: `uvicorn data_core.asgi:app`."""

import logging

from data_core.main import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = create_app()
