"""Slug identifiant sur l'automate (préremplí du label, normalisé, éditable).

Le slug est un identifiant lisible et stable côté IHM. Les lignes existantes
sont rétro-remplies avec leur id (garanti unique) avant d'ajouter l'unicité.

Revision ID: 090
Revises: 089
Create Date: 2026-08-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "090"
down_revision: str | None = "089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "automation",
        sa.Column("slug", sa.Text(), nullable=False, server_default=""),
    )
    # Rétro-remplissage : slug = id (unique) pour ne pas violer l'unicité.
    op.execute("UPDATE automation SET slug = id WHERE slug = ''")
    op.create_index("uq_automation_slug", "automation", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_automation_slug", table_name="automation")
    op.drop_column("automation", "slug")
