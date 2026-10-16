import pytest
from sqlalchemy.pool import NullPool, QueuePool

from data_core.db.session import make_engine, normalize_database_url
from data_core.main import create_app


def test_sqlite_is_rejected_on_vercel(settings, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(RuntimeError, match="Postgres"):
        create_app(settings)


def test_null_pool_when_configured(settings, monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    app = create_app(settings.model_copy(update={"db_null_pool": True}))
    assert isinstance(app.state.engine.pool, NullPool)
    app.state.services.close()


def test_default_pool_outside_vercel(settings, monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    app = create_app(settings)
    assert isinstance(app.state.engine.pool, QueuePool)
    app.state.services.close()


@pytest.mark.parametrize(
    "url",
    [
        "postgres://u:p@ep-x-pooler.neon.tech/db?sslmode=require",
        "postgresql://u:p@ep-x-pooler.neon.tech/db?sslmode=require",
    ],
)
def test_neon_urls_use_psycopg3_with_null_pool(url):
    assert normalize_database_url(url).startswith("postgresql+psycopg://")
    engine = make_engine(url, null_pool=True)  # no connection is opened here
    assert engine.dialect.driver == "psycopg"
    assert isinstance(engine.pool, NullPool)
