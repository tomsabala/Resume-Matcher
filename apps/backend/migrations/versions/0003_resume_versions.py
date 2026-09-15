"""Append-only resume version history.

Every content write lands a snapshot row; ``resumes.head_version_id`` points
at the newest one so the read path never sorts the history.

Revision ID: 0003_resume_versions
Revises: 0002_workspaces
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_resume_versions"
down_revision: str | None = "0002_workspaces"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resume_versions",
        sa.Column("version_id", sa.String(), nullable=False),
        sa.Column("resume_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("parent_version_id", sa.String(), nullable=True),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("tex_source", sa.Text(), nullable=True),
        sa.Column(
            "tex_source_mode", sa.String(), nullable=False, server_default="generated"
        ),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("origin_ref", sa.String(), nullable=True),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("version_id"),
    )
    op.create_index(
        "ix_versions_resume_created",
        "resume_versions",
        ["resume_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_versions_workspace", "resume_versions", ["workspace_id"], unique=False
    )
    op.add_column("resumes", sa.Column("head_version_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("resumes", "head_version_id")
    op.drop_index("ix_versions_workspace", table_name="resume_versions")
    op.drop_index("ix_versions_resume_created", table_name="resume_versions")
    op.drop_table("resume_versions")
