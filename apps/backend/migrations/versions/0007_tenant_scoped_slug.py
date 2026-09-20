"""Workspace slugs become unique per tenant instead of across the table.

``ux_workspaces_slug`` made the slug namespace global, so ``_insert_workspace``
de-duplicated against every tenant's rows. That turned workspace creation into
a cross-tenant oracle: asking for "Lior" and being handed ``lior-2`` proved
another tenant already owned ``lior``. The replacement key is
``(tenant_ref, slug)``.

The upgrade is a pure relaxation — a globally unique column is already unique
per tenant — so no data has to move.

The downgrade is not: two tenants may by then hold the same slug. Rather than
fail, it renames the later duplicates (``slug-2``, ``slug-3``, … by creation
order) before restoring the global index. Slugs are display/identity sugar,
never a foreign key, so a rename is safe.

Revision ID: 0007_tenant_scoped_slug
Revises: 0006_tenancy
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_tenant_scoped_slug"
down_revision: str | None = "0006_tenancy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspaces", schema=None) as batch_op:
        batch_op.drop_index("ux_workspaces_slug")
        batch_op.create_index(
            "ux_workspaces_tenant_slug", ["tenant_ref", "slug"], unique=True
        )


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT workspace_id, slug FROM workspaces"
            " ORDER BY created_at, workspace_id"
        )
    ).all()
    taken: set[str] = set()
    for workspace_id, slug in rows:
        candidate = slug
        suffix = 2
        while candidate in taken:
            candidate = f"{slug}-{suffix}"
            suffix += 1
        taken.add(candidate)
        if candidate != slug:
            conn.execute(
                sa.text(
                    "UPDATE workspaces SET slug = :slug WHERE workspace_id = :id"
                ).bindparams(slug=candidate, id=workspace_id)
            )

    with op.batch_alter_table("workspaces", schema=None) as batch_op:
        batch_op.drop_index("ux_workspaces_tenant_slug")
        batch_op.create_index("ux_workspaces_slug", ["slug"], unique=True)
