"""Replay revision ``0006_tenancy`` against a database built by ``0005``.

The only test in the repo that runs the migrations, and the only thing that can
catch a botched ``api_keys`` rebuild. ``db_engine._create_at_head`` builds every
other test's database with ``Base.metadata.create_all``, so no other test
exercises a revision at all, and ``alembic check`` does not diff primary-key
constraints — it would pass with the old single-column key in place.

What matters here is the parts of the revision that are not a plain column add:
the two backfills that join through resumes and jobs, and the table rebuild that
turns ``api_keys``' primary key into ``(workspace_id, provider)``.
"""

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config

pytestmark = pytest.mark.integration

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(data_dir: Path) -> Config:
    config = Config(BACKEND_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{data_dir / 'resume_matcher.db'}")
    return config


def _seed_pre_tenancy(connection: sqlite3.Connection) -> dict[str, str]:
    """Insert one row per affected table, as revision 0005's schema allows.

    Raw SQL on purpose: the ORM models describe the *post*-migration shape, so
    using them here would hide exactly the drift this test exists to catch.
    """
    default_id = connection.execute(
        "SELECT workspace_id FROM workspaces WHERE is_default = 1"
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO workspaces"
        " (workspace_id, name, slug, content_language, is_default, created_at, updated_at)"
        " VALUES ('ws-second', 'Second', 'second', 'en', 0, 't', 't')"
    )
    connection.execute(
        "INSERT INTO resumes"
        " (resume_id, workspace_id, content, content_type, is_master,"
        "  processing_status, created_at, updated_at)"
        " VALUES ('r-second', 'ws-second', '{}', 'json', 0, 'ready', 't', 't')"
    )
    connection.execute(
        "INSERT INTO jobs (job_id, workspace_id, content, created_at, metadata_json)"
        " VALUES ('j-default', ?, 'jd', 't', '{}')",
        (default_id,),
    )
    # Joins to its workspace through original_resume_id.
    connection.execute(
        "INSERT INTO improvements"
        " (request_id, original_resume_id, tailored_resume_id, job_id, improvements,"
        "  created_at)"
        " VALUES ('imp-joined', 'r-second', 'gone', 'j-default', '[]', 't')"
    )
    # Resume is gone; joins only through the job.
    connection.execute(
        "INSERT INTO improvements"
        " (request_id, original_resume_id, tailored_resume_id, job_id, improvements,"
        "  created_at)"
        " VALUES ('imp-via-job', 'gone', 'gone', 'j-default', '[]', 't')"
    )
    # A true orphan: delete_resume and delete_job have always left these behind.
    connection.execute(
        "INSERT INTO improvements"
        " (request_id, original_resume_id, tailored_resume_id, job_id, improvements,"
        "  created_at)"
        " VALUES ('imp-orphan', 'gone', 'gone', 'gone', '[]', 't')"
    )
    connection.execute(
        "INSERT INTO tailoring_previews"
        " (preview_id, source_id, job_id, payload_hash, source_hash, job_hash,"
        "  created_at, expires_at)"
        " VALUES ('p-joined', 'r-second', 'j-default', 'h', 'h', 'h', 't', 't')"
    )
    connection.execute(
        "INSERT INTO tailoring_previews"
        " (preview_id, source_id, job_id, payload_hash, source_hash, job_hash,"
        "  created_at, expires_at)"
        " VALUES ('p-orphan', 'gone', 'gone', 'h', 'h', 'h', 't', 't')"
    )
    connection.execute(
        "INSERT INTO api_keys (provider, ciphertext, updated_at)"
        " VALUES ('google', 'cipher', 't')"
    )
    connection.commit()
    return {"default_id": str(default_id)}


@pytest.fixture
def migrated(tmp_path: Path) -> Any:
    """A database upgraded 0005 → head with pre-tenancy rows already in it."""
    # Its own directory: the autouse isolation fixture already owns
    # ``tmp_path / "data"`` for the per-test application database.
    data_dir = tmp_path / "migration"
    data_dir.mkdir(parents=True)
    config = _alembic_config(data_dir)
    command.upgrade(config, "0005_template_settings")

    connection = sqlite3.connect(data_dir / "resume_matcher.db")
    try:
        seeded = _seed_pre_tenancy(connection)
    finally:
        connection.close()

    command.upgrade(config, "head")
    connection = sqlite3.connect(data_dir / "resume_matcher.db")
    try:
        yield connection, seeded, config, data_dir
    finally:
        connection.close()


def test_the_workspaces_table_gains_the_tenancy_columns(migrated: Any) -> None:
    connection, _, _, _ = migrated
    columns = {
        row[1]: row for row in connection.execute("PRAGMA table_info(workspaces)")
    }
    assert {"tenant_ref", "is_anonymous", "last_seen_at"} <= set(columns)
    # NOT NULL with an empty-string sentinel is load-bearing: the partial
    # unique index below treats NULLs as distinct, so a nullable tenant_ref
    # would silently stop enforcing one default per tenant.
    assert columns["tenant_ref"][3] == 1
    rows = connection.execute(
        "SELECT tenant_ref, is_anonymous, last_seen_at FROM workspaces"
    ).fetchall()
    assert all(row[0] == "" and row[1] == 0 and row[2] for row in rows)


def test_the_default_index_becomes_per_tenant(migrated: Any) -> None:
    connection, _, _, _ = migrated
    indexes = {
        row[0]: row[1]
        for row in connection.execute(
            "SELECT name, sql FROM sqlite_master"
            " WHERE type = 'index' AND tbl_name = 'workspaces'"
        )
    }
    assert "ux_workspaces_single_default" not in indexes
    assert "tenant_ref" in indexes["ux_workspaces_tenant_default"]

    # Two tenants may each hold a default; one tenant may not hold two.
    connection.execute(
        "UPDATE workspaces SET tenant_ref = 'anon-1' WHERE workspace_id = 'ws-second'"
    )
    connection.execute(
        "UPDATE workspaces SET is_default = 1 WHERE workspace_id = 'ws-second'"
    )
    connection.commit()
    # SQLite enforces a unique index at statement time, not at commit.
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO workspaces"
            " (workspace_id, name, slug, content_language, is_default, tenant_ref,"
            "  is_anonymous, last_seen_at, created_at, updated_at)"
            " VALUES ('ws-third', 'Third', 'third', 'en', 1, 'anon-1', 1, 't', 't', 't')"
        )


def test_improvements_are_backfilled_through_resume_then_job(migrated: Any) -> None:
    connection, seeded, _, _ = migrated
    scopes = dict(
        connection.execute("SELECT request_id, workspace_id FROM improvements")
    )
    assert scopes["imp-joined"] == "ws-second"
    assert scopes["imp-via-job"] == seeded["default_id"]
    # Historical orphans cannot be joined to anything, so they land on the
    # default workspace. Inert history, documented in the revision.
    assert scopes["imp-orphan"] == seeded["default_id"]
    assert not connection.execute(
        "SELECT 1 FROM improvements WHERE workspace_id = ''"
    ).fetchall()


def test_previews_are_backfilled_the_same_way(migrated: Any) -> None:
    connection, seeded, _, _ = migrated
    scopes = dict(
        connection.execute("SELECT preview_id, workspace_id FROM tailoring_previews")
    )
    assert scopes["p-joined"] == "ws-second"
    assert scopes["p-orphan"] == seeded["default_id"]
    assert not connection.execute(
        "SELECT 1 FROM tailoring_previews WHERE workspace_id = ''"
    ).fetchall()


def test_api_keys_gains_a_composite_primary_key(migrated: Any) -> None:
    connection, seeded, _, _ = migrated
    primary_key = [
        row[1] for row in connection.execute("PRAGMA table_info(api_keys)") if row[5]
    ]
    assert set(primary_key) == {"workspace_id", "provider"}

    # The existing key becomes the default workspace's, not an orphan.
    assert connection.execute(
        "SELECT workspace_id FROM api_keys WHERE provider = 'google'"
    ).fetchone()[0] == seeded["default_id"]

    # The whole point of the rebuild: a second workspace may hold the same
    # provider. Under the old single-column key this insert failed.
    connection.execute(
        "INSERT INTO api_keys (workspace_id, provider, ciphertext, updated_at)"
        " VALUES ('ws-second', 'google', 'other', 't')"
    )
    connection.commit()
    assert (
        connection.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0] == 2
    )

    # Enforced at statement time, so the raise is on execute, not commit.
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO api_keys (workspace_id, provider, ciphertext, updated_at)"
            " VALUES ('ws-second', 'google', 'dupe', 't')"
        )


def test_workspace_settings_starts_empty(migrated: Any) -> None:
    """An absent row means "instance default", which is right for the
    pre-existing tenant — so the revision must not seed from config.json."""
    connection, _, _, _ = migrated
    primary_key = {
        row[1]
        for row in connection.execute("PRAGMA table_info(workspace_settings)")
        if row[5]
    }
    assert primary_key == {"workspace_id", "key"}
    assert connection.execute("SELECT COUNT(*) FROM workspace_settings").fetchone()[
        0
    ] == 0


def test_the_revision_is_reversible(migrated: Any) -> None:
    """Downgrade restores 0005's shape, losing only what it must.

    A single-column ``provider`` key cannot hold two tenants' keys, so the
    non-default workspace's are dropped; the revision's docstring says so.
    """
    connection, _, config, data_dir = migrated
    connection.execute(
        "INSERT INTO api_keys (workspace_id, provider, ciphertext, updated_at)"
        " VALUES ('ws-second', 'google', 'other', 't')"
    )
    connection.commit()
    connection.close()

    command.downgrade(config, "0005_template_settings")

    reopened = sqlite3.connect(data_dir / "resume_matcher.db")
    try:
        columns = {row[1] for row in reopened.execute("PRAGMA table_info(api_keys)")}
        assert "workspace_id" not in columns
        assert reopened.execute("SELECT provider FROM api_keys").fetchall() == [
            ("google",)
        ]
        workspace_columns = {
            row[1] for row in reopened.execute("PRAGMA table_info(workspaces)")
        }
        assert not {"tenant_ref", "is_anonymous", "last_seen_at"} & workspace_columns
        assert not reopened.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'workspace_settings'"
        ).fetchall()
    finally:
        reopened.close()

    # And forward again, so a downgrade is not a one-way door.
    command.upgrade(config, "head")
