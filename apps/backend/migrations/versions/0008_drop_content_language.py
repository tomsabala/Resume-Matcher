"""Drop ``workspaces.content_language``.

Resume generation is English-in / English-out, so the per-workspace content
language has no reader left: the config endpoints, the prompt bridge and the
frontend selector are all gone. The column is display-only data — nothing
references it — so dropping it moves no rows.

SQLite has supported ``ALTER TABLE … DROP COLUMN`` since 3.35, which is older
than the 3.37 shipped with the supported Python 3.13 environments, so this is a
plain drop rather than a batch-mode table rebuild.

Revision ID: 0008_drop_content_language
Revises: 0007_tenant_scoped_slug
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_drop_content_language"
down_revision: str | None = "0007_tenant_scoped_slug"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("workspaces", "content_language")


def downgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "content_language",
            sa.String(),
            nullable=False,
            server_default="en",
        ),
    )
