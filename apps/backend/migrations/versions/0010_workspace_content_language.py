"""Re-add ``workspaces.content_language``.

Hebrew lands as a supported *content* language: a workspace declares the
language everything the app generates for it is written in. ``0008`` dropped
the column when generation was English-only; this restores it with the same
shape, so the pair is an exact inverse.

``server_default="en"`` is load-bearing. Rows inserted by raw SQL that predates
this column (and the migration tests that do exactly that) must keep working,
and a NOT NULL column without a default would break them.

Revision ID: 0010_workspace_content_language
Revises: 0009_prep_cards
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_workspace_content_language"
down_revision: str | None = "0009_prep_cards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "content_language",
            sa.String(),
            nullable=False,
            server_default="en",
        ),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "content_language")
