"""Vercel entrypoint: the whole FastAPI app runs as one Python serverless function (see vercel.json)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_core.asgi import app  # noqa: E402,F401
