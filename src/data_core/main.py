from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from data_core import __version__
from data_core.api import cases, internal, observations, requests, sensors
from data_core.config import Settings, get_settings, running_on_vercel
from data_core.db.base import Base
from data_core.db.session import make_engine, make_sessionmaker
from data_core.services import Services, build_services

DESCRIPTION = """
Data-Sync & Core of the Farmer Advisory & Early-Warning System.

* **Raspberry Pi / field sensors** push readings to `POST /v1/sensor-readings`.
* **Phone / Telegram system** submits structured caller input to `POST /v1/requests`.
* The core plans which data is needed, gathers sensor readings, previous caller reports and weather,
  calls the external **recommender**, stores the result and pushes it to the **dashboard** and
  **phone system** via signed webhooks.
"""


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    """App factory. Everything is initialised eagerly (not only in lifespan) so the app also works on
    serverless runtimes that don't run ASGI lifespan events."""
    settings = settings or get_settings()
    on_vercel = running_on_vercel()
    if on_vercel and settings.database_url.startswith("sqlite"):
        raise RuntimeError(
            "DATABASE_URL points to SQLite, which can't persist on Vercel. "
            "Set DATABASE_URL to a Postgres URL (e.g. Neon from the Vercel Marketplace)."
        )
    engine = make_engine(settings.database_url, null_pool=settings.db_null_pool or on_vercel)
    if settings.create_tables_on_startup:
        Base.metadata.create_all(engine)
    services = services or build_services(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        app.state.services.close()
        engine.dispose()

    app = FastAPI(title="Data-Sync & Core", version=__version__, description=DESCRIPTION, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.services = services

    for module in (sensors, requests, cases, observations, internal):
        app.include_router(module.router)

    @app.get("/health", tags=["ops"])
    def health():
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:
            return JSONResponse(status_code=503, content={"status": "error", "db": str(exc)})
        return {"status": "ok", "db": "ok", "version": __version__}

    return app
