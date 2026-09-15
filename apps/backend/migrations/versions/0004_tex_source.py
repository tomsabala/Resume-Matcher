"""Hand-edited LaTeX override on resumes.

NULL means "generate the .tex from the document". A non-null value is the
user's own source and wins over generation until they clear it.

Revision ID: 0004_tex_source
Revises: 0003_resume_versions
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_tex_source"
down_revision: str | None = "0003_resume_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("resumes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("tex_source", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("resumes", schema=None) as batch_op:
        batch_op.drop_column("tex_source")
