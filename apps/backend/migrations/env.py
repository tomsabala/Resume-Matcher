"""Alembic environment for the SQLite store.

Two entry modes:

* **CLI** (``alembic upgrade head`` from ``apps/backend``) — builds its own
  engine from ``settings.sqlite_path``.
* **Programmatic** (``app.db_engine.init_models_sync``) — the caller puts a live
  ``Connection`` in ``config.attributes["connection"]`` so the migration runs on
  the same engine the application already opened, with its PRAGMAs applied.

``render_as_batch`` is on because SQLite cannot ``ALTER``/``DROP`` a column in
place; batch mode rewrites the table instead.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.models import Base

config = context.config

if config.config_file_name is not None and config.attributes.get("connection") is None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    configured = config.get_main_option("sqlalchemy.url", "")
    if configured:
        return configured
    path = settings.sqlite_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DBAPI connection."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    engine = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    try:
        with engine.connect() as conn:
            _run(conn)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
