from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool


def normalize_database_url(url: str) -> str:
    """Hosted Postgres (Neon, Supabase, Azure) hands out postgres:// URLs; use the psycopg 3 driver."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def make_engine(database_url: str, null_pool: bool = False) -> Engine:
    """`null_pool=True` opens a fresh connection per checkout - right for serverless (Vercel), where
    instances freeze between requests and pooling is done by the DB provider (e.g. Neon's PgBouncer)."""
    url = normalize_database_url(database_url)
    is_sqlite = url.startswith("sqlite")
    kwargs: dict = {"pool_pre_ping": True}
    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
    elif url.startswith("postgresql+psycopg"):
        # No server-side prepared statements: they break behind transaction-mode poolers (PgBouncer).
        kwargs["connect_args"] = {"prepare_threshold": None}
    if null_pool:
        kwargs["poolclass"] = NullPool
    engine = create_engine(url, **kwargs)

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_conn, _record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
