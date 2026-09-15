"""Workspaces: scope resumes, jobs and applications to a named owner profile.

Also replaces the database-global single-master invariant
(``ux_resumes_single_master``) with a per-workspace one, since every workspace
owns its own master resume.

Revision ID: 0002_workspaces
Revises: 0001_baseline
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0002_workspaces"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCOPED_TABLES = ("resumes", "jobs", "applications")


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("content_language", sa.String(), nullable=False, server_default="en"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id"),
    )
    op.create_index("ux_workspaces_slug", "workspaces", ["slug"], unique=True)
    op.create_index(
        "ux_workspaces_single_default",
        "workspaces",
        ["is_default"],
        unique=True,
        sqlite_where=sa.text("is_default = 1"),
    )

    default_id = uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    op.execute(
        sa.text(
            "INSERT INTO workspaces"
            " (workspace_id, name, slug, content_language, is_default, created_at, updated_at)"
            " VALUES (:id, 'Default', 'default', 'en', 1, :now, :now)"
        ).bindparams(id=default_id, now=now)
    )

    for table in _SCOPED_TABLES:
        op.add_column(
            table,
            sa.Column("workspace_id", sa.String(), nullable=False, server_default=""),
        )
        op.execute(
            sa.text(f"UPDATE {table} SET workspace_id = :id").bindparams(id=default_id)
        )
        op.create_index(f"ix_{table}_workspace", table, ["workspace_id"], unique=False)

    with op.batch_alter_table("resumes", schema=None) as batch_op:
        batch_op.drop_index("ux_resumes_single_master", sqlite_where=sa.text("is_master = 1"))
        batch_op.create_index(
            "ux_resumes_workspace_master",
            ["workspace_id", "is_master"],
            unique=True,
            sqlite_where=sa.text("is_master = 1"),
        )


def downgrade() -> None:
    with op.batch_alter_table("resumes", schema=None) as batch_op:
        batch_op.drop_index("ux_resumes_workspace_master", sqlite_where=sa.text("is_master = 1"))
        batch_op.create_index(
            "ux_resumes_single_master",
            ["is_master"],
            unique=True,
            sqlite_where=sa.text("is_master = 1"),
        )

    for table in _SCOPED_TABLES:
        op.drop_index(f"ix_{table}_workspace", table_name=table)
        op.drop_column(table, "workspace_id")

    op.drop_index("ux_workspaces_single_default", table_name="workspaces")
    op.drop_index("ux_workspaces_slug", table_name="workspaces")
    op.drop_table("workspaces")
