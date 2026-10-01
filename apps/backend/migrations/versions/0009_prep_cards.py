"""Interview-prep flashcard deck.

A workspace-global deck of question cards. ``technical`` cards are studied as a
flip-card game; ``personal`` cards are rehearsed by writing an answer and asking
the LLM to critique it. Distinct from the per-resume ``interview_prep`` column.

Revision ID: 0009_prep_cards
Revises: 0008_drop_content_language
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_prep_cards"
down_revision: str | None = "0008_drop_content_language"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prep_cards",
        sa.Column("card_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False, server_default=""),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("examples", sa.JSON(), nullable=True),
        sa.Column("my_answer", sa.Text(), nullable=True),
        sa.Column("critique", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("application_id", sa.String(), nullable=True),
        sa.Column("reviewed_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("card_id"),
    )
    with op.batch_alter_table("prep_cards", schema=None) as batch_op:
        batch_op.create_index("ix_prep_cards_workspace", ["workspace_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_prep_cards_category"), ["category"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_prep_cards_application_id"), ["application_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("prep_cards", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_prep_cards_application_id"))
        batch_op.drop_index(batch_op.f("ix_prep_cards_category"))
        batch_op.drop_index("ix_prep_cards_workspace")
    op.drop_table("prep_cards")
