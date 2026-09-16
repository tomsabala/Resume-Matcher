"""Per-resume template and formatting settings.

NULL means the user has not chosen for this resume yet; the client then falls
back to its last-used settings. Presentation only, so it is not versioned.

Revision ID: 0005_template_settings
Revises: 0004_tex_source
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_template_settings"
down_revision: str | None = "0004_tex_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("resumes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("template_settings", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("resumes", schema=None) as batch_op:
        batch_op.drop_column("template_settings")
