"""Alembic environment. The DB URL comes from DATABASE_URL (data_core.config), never from alembic.ini."""

from logging.config import fileConfig

from alembic import context

from data_core.config import Settings
from data_core.db import models  # noqa: F401  (registers tables on Base.metadata)
from data_core.db.base import Base
from data_core.db.session import make_engine, normalize_database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
DATABASE_URL = Settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=normalize_database_url(DATABASE_URL),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(DATABASE_URL)
    with engine.connect() as connection:
        # render_as_batch lets ALTERs work on SQLite too
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
