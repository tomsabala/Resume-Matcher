"""Shared tenancy: group workspaces by tenant, scope the remaining tables.

Three things change shape:

* ``workspaces`` gains ``tenant_ref`` (the identity a profile belongs to, with
  ``""`` meaning the standalone/single-mode tenant), ``is_anonymous`` and
  ``last_seen_at``, and the single-default partial unique index becomes a
  per-tenant one.
* ``improvements`` and ``tailoring_previews`` gain the ``workspace_id`` every
  other document table already carries, so the facade can scope them.
* ``api_keys`` is rebuilt with a ``(workspace_id, provider)`` primary key, and
  ``workspace_settings`` is created for per-tenant overrides of ``config.json``.

Two caveats worth knowing before reading the backfills:

* **Historical orphans fall back to the default workspace.** ``delete_resume``
  and ``delete_job`` have always removed parent rows without touching
  ``improvements`` or ``tailoring_previews``, so rows whose resume and job are
  both gone exist. They cannot be joined to a workspace and are stamped with
  the default one. They are inert history (nothing reads an improvement whose
  tailored resume no longer exists), so this is accepted rather than deleted.
* **The downgrade is lossy for API keys.** A single-column ``provider`` primary
  key cannot hold two tenants' keys for the same provider, so every non-default
  workspace's keys are dropped before the table is rebuilt. Downgrading also
  drops every per-tenant setting override.

Revision ID: 0006_tenancy
Revises: 0005_template_settings
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "0006_tenancy"
down_revision: str | None = "0005_template_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _default_workspace_id(conn: sa.engine.Connection) -> str:
    """The workspace historical rows belong to.

    ``0002_workspaces`` seeds exactly one default row and every document row
    was stamped with it, so this is the only sane fallback for a row that
    cannot be joined to a workspace of its own.
    """
    found = conn.execute(
        sa.text("SELECT workspace_id FROM workspaces WHERE is_default = 1 LIMIT 1")
    ).scalar()
    if found:
        return str(found)
    found = conn.execute(
        sa.text("SELECT workspace_id FROM workspaces ORDER BY created_at LIMIT 1")
    ).scalar()
    return str(found) if found else ""


# ``api_keys`` as ``0001_baseline`` created it. Batch mode has to be told the
# source shape explicitly: reflecting it would carry the unnamed single-column
# PrimaryKeyConstraint("provider") into the rebuilt table, silently keeping the
# old primary key. The name is synthetic — SQLite does not store primary-key
# constraint names — and exists only so the rebuild can drop the old key
# before declaring the new one.
_API_KEYS_BEFORE = sa.Table(
    "api_keys",
    sa.MetaData(),
    sa.Column("provider", sa.String(), nullable=False),
    sa.Column("ciphertext", sa.Text(), nullable=False),
    sa.Column("updated_at", sa.String(), nullable=False),
    sa.PrimaryKeyConstraint("provider", name="pk_api_keys"),
)

_API_KEYS_AFTER = sa.Table(
    "api_keys",
    sa.MetaData(),
    sa.Column("workspace_id", sa.String(), nullable=False),
    sa.Column("provider", sa.String(), nullable=False),
    sa.Column("ciphertext", sa.Text(), nullable=False),
    sa.Column("updated_at", sa.String(), nullable=False),
    sa.PrimaryKeyConstraint("workspace_id", "provider", name="pk_api_keys"),
)


def upgrade() -> None:
    conn = op.get_bind()
    default_id = _default_workspace_id(conn)
    now = datetime.now(timezone.utc).isoformat()

    # -- workspaces: tenant grouping and anonymous lifecycle ----------------
    op.add_column(
        "workspaces",
        sa.Column("tenant_ref", sa.String(), nullable=False, server_default=""),
    )
    op.add_column(
        "workspaces",
        sa.Column(
            "is_anonymous", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column(
        "workspaces",
        sa.Column("last_seen_at", sa.String(), nullable=False, server_default=""),
    )
    op.execute(
        sa.text("UPDATE workspaces SET last_seen_at = :now WHERE last_seen_at = ''")
        .bindparams(now=now)
    )
    op.create_index("ix_workspaces_tenant", "workspaces", ["tenant_ref"], unique=False)
    with op.batch_alter_table("workspaces", schema=None) as batch_op:
        batch_op.drop_index(
            "ux_workspaces_single_default", sqlite_where=sa.text("is_default = 1")
        )
        batch_op.create_index(
            "ux_workspaces_tenant_default",
            ["tenant_ref", "is_default"],
            unique=True,
            sqlite_where=sa.text("is_default = 1"),
        )

    # -- improvements: join to the workspace through resume, then job -------
    op.add_column(
        "improvements",
        sa.Column("workspace_id", sa.String(), nullable=False, server_default=""),
    )
    op.create_index(
        "ix_improvements_workspace", "improvements", ["workspace_id"], unique=False
    )
    op.execute(
        sa.text(
            "UPDATE improvements SET workspace_id = COALESCE("
            " (SELECT r.workspace_id FROM resumes r"
            "   WHERE r.resume_id = improvements.original_resume_id),"
            " (SELECT r.workspace_id FROM resumes r"
            "   WHERE r.resume_id = improvements.tailored_resume_id),"
            " (SELECT j.workspace_id FROM jobs j WHERE j.job_id = improvements.job_id),"
            " :default_id)"
        ).bindparams(default_id=default_id)
    )

    # -- tailoring_previews: same, through source, result, then job ---------
    op.add_column(
        "tailoring_previews",
        sa.Column("workspace_id", sa.String(), nullable=False, server_default=""),
    )
    op.create_index(
        "ix_previews_workspace", "tailoring_previews", ["workspace_id"], unique=False
    )
    op.execute(
        sa.text(
            "UPDATE tailoring_previews SET workspace_id = COALESCE("
            " (SELECT r.workspace_id FROM resumes r"
            "   WHERE r.resume_id = tailoring_previews.source_id),"
            " (SELECT r.workspace_id FROM resumes r"
            "   WHERE r.resume_id = tailoring_previews.result_resume_id),"
            " (SELECT j.workspace_id FROM jobs j"
            "   WHERE j.job_id = tailoring_previews.job_id),"
            " :default_id)"
        ).bindparams(default_id=default_id)
    )

    # -- api_keys: (workspace_id, provider) primary key ---------------------
    with op.batch_alter_table(
        "api_keys", copy_from=_API_KEYS_BEFORE, recreate="always"
    ) as batch_op:
        batch_op.drop_constraint("pk_api_keys", type_="primary")
        batch_op.add_column(
            sa.Column(
                "workspace_id",
                sa.String(),
                nullable=False,
                server_default=default_id,
            )
        )
        batch_op.create_primary_key("pk_api_keys", ["workspace_id", "provider"])

    # -- workspace_settings: per-tenant config.json overrides ---------------
    # Deliberately not seeded from config.json: an absent row means "use the
    # instance default", which is exactly right for the pre-existing tenant.
    op.create_table(
        "workspace_settings",
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "key"),
    )


def downgrade() -> None:
    conn = op.get_bind()
    default_id = _default_workspace_id(conn)

    op.drop_table("workspace_settings")

    # A single-column provider key cannot hold two tenants' keys, so only the
    # default workspace's survive.
    op.execute(
        sa.text("DELETE FROM api_keys WHERE workspace_id <> :default_id").bindparams(
            default_id=default_id
        )
    )
    with op.batch_alter_table(
        "api_keys", copy_from=_API_KEYS_AFTER, recreate="always"
    ) as batch_op:
        batch_op.drop_constraint("pk_api_keys", type_="primary")
        batch_op.drop_column("workspace_id")
        batch_op.create_primary_key("pk_api_keys", ["provider"])

    op.drop_index("ix_previews_workspace", table_name="tailoring_previews")
    op.drop_column("tailoring_previews", "workspace_id")

    op.drop_index("ix_improvements_workspace", table_name="improvements")
    op.drop_column("improvements", "workspace_id")

    with op.batch_alter_table("workspaces", schema=None) as batch_op:
        batch_op.drop_index(
            "ux_workspaces_tenant_default", sqlite_where=sa.text("is_default = 1")
        )
        batch_op.create_index(
            "ux_workspaces_single_default",
            ["is_default"],
            unique=True,
            sqlite_where=sa.text("is_default = 1"),
        )
    op.drop_index("ix_workspaces_tenant", table_name="workspaces")
    op.drop_column("workspaces", "last_seen_at")
    op.drop_column("workspaces", "is_anonymous")
    op.drop_column("workspaces", "tenant_ref")
