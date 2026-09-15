"""SQLite engine/session plumbing for the SQLAlchemy data layer.

Every ``Database`` instance owns its own engines (one async for the document
tables, one sync for the encrypted ``api_keys`` table read on the synchronous
LLM hot path) built from these factories. Keeping construction here lets tests
spin up fully isolated engines against a temp-file database.
"""

from datetime import datetime, timezone
from functools import cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.models import Base

__all__ = ["Base", "make_async_engine", "make_sync_engine", "init_models_sync"]

# The revision whose schema a pre-Alembic database already has on disk.
_BASELINE_REVISION = "0001_baseline"


def _apply_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
    """Set per-connection SQLite PRAGMAs.

    WAL improves concurrent read/write between the async (doc tables) and sync
    (api_keys) engines pointed at the same file; ``busy_timeout`` rides out the
    brief lock contention that creates; ``foreign_keys`` enforces relational
    integrity (off by default in SQLite).
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def _url(path: Path, *, driver: str) -> str:
    """Build a SQLite URL. Absolute paths yield the required four slashes."""
    return f"sqlite+{driver}:///{path}" if driver else f"sqlite:///{path}"


def make_async_engine(path: Path) -> AsyncEngine:
    """Create the async engine (``aiosqlite``) for the document tables."""
    engine = create_async_engine(_url(path, driver="aiosqlite"), future=True)
    event.listen(engine.sync_engine, "connect", _apply_sqlite_pragmas)
    return engine


def make_sync_engine(path: Path) -> Engine:
    """Create the sync engine used for the encrypted api_keys table.

    Key reads happen synchronously (``get_llm_config`` → ``load_config_file`` →
    ``resolve_api_key``), so a sync engine avoids threading async through
    ``llm.py``. It points at the same file as the async engine.
    """
    engine = create_engine(_url(path, driver=""), future=True)
    event.listen(engine, "connect", _apply_sqlite_pragmas)
    return engine


@cache
def _alembic_config() -> Config:
    """Load ``alembic.ini`` from the backend package root (cached: parsing it
    on every ``Database`` construction would cost one file read per test)."""
    return Config(Path(__file__).resolve().parent.parent / "alembic.ini")


def _patch_pre_alembic_schema(conn: Connection) -> None:
    """Bring a pre-Alembic database up to the baseline revision's shape.

    These are the three hand-written idempotent patches that ``init_models_sync``
    applied before Alembic existed. A database created by an older build may be
    missing any of them, so they run once, immediately before the stamp.
    """
    columns = conn.exec_driver_sql("PRAGMA table_info(resumes)").mappings().all()
    existing_columns = {column["name"] for column in columns}
    if columns and "interview_prep" not in existing_columns:
        conn.exec_driver_sql("ALTER TABLE resumes ADD COLUMN interview_prep TEXT")
    if columns and "processing_token" not in existing_columns:
        conn.exec_driver_sql("ALTER TABLE resumes ADD COLUMN processing_token TEXT")

    preview_columns = conn.exec_driver_sql("PRAGMA table_info(tailoring_previews)").mappings().all()
    if preview_columns:
        if "improvements" not in {column["name"] for column in preview_columns}:
            conn.exec_driver_sql("ALTER TABLE tailoring_previews ADD COLUMN improvements JSON")
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_preview_compatibility"
            " ON tailoring_previews (source_id, job_id, payload_hash, created_at)"
        )


@cache
def _head_revision() -> str:
    """Revision id of the migration head, resolved once per process."""
    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    assert head is not None, "migrations/versions is empty"
    return head


def _create_at_head(conn: Connection) -> None:
    """Build a brand-new database from the models and stamp it at head.

    Equivalent to replaying every migration — ``alembic check`` is what keeps
    the two definitions from drifting — but ~10x cheaper, which matters because
    every test builds its own database. The default workspace row is seeded
    here for the same reason revision ``0002_workspaces`` seeds it: every
    document row is scoped to a workspace, so one must always exist.
    """
    Base.metadata.create_all(conn)
    conn.exec_driver_sql(
        "CREATE TABLE alembic_version ("
        " version_num VARCHAR(32) NOT NULL,"
        " CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
    )
    conn.exec_driver_sql(
        "INSERT INTO alembic_version (version_num) VALUES (?)", (_head_revision(),)
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.exec_driver_sql(
        "INSERT INTO workspaces"
        " (workspace_id, name, slug, content_language, is_default, created_at, updated_at)"
        " VALUES (?, 'Default', 'default', 'en', 1, ?, ?)",
        (uuid4().hex, now, now),
    )


def init_models_sync(engine: Engine) -> None:
    """Bring the database schema to ``head`` (idempotent).

    Three cases:

    * **Empty file** — created straight from the models and stamped at head.
    * **Tables but no ``alembic_version``** — a pre-Alembic database: patched to
      the baseline shape and stamped there, so the baseline revision never
      tries to re-create tables that hold the user's data, then upgraded.
    * **Alembic-managed** — upgraded only when it is behind head. The common
      case costs one ``SELECT``.
    """
    config = _alembic_config()
    with engine.begin() as conn:
        tables = set(inspect(conn).get_table_names())
        if not tables:
            _create_at_head(conn)
            return
        if "alembic_version" not in tables:
            _patch_pre_alembic_schema(conn)
            config.attributes["connection"] = conn
            command.stamp(config, _BASELINE_REVISION)
        elif conn.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar() == _head_revision():
            return
        config.attributes["connection"] = conn
        try:
            command.upgrade(config, "head")
        finally:
            config.attributes.pop("connection", None)
