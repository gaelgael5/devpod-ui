"""MCO — horodatage de révocation des clés API (base de la purge à 24h).

La révocation d'une clé API (`mcp_apikey`) était un simple flag booléen `revoked`
sans date : impossible de savoir *quand* une clé avait été révoquée, donc de purger
« les clés révoquées depuis plus de 24h ». Cette migration ajoute `revoked_at`,
renseigné à la révocation ; une purge périodique supprime ensuite les clés révoquées
au-delà de la rétention.

Les clés déjà révoquées avant cette migration ont `revoked_at` NULL : la purge
retombe sur `created_at` pour elles (COALESCE), sans backfill.

Revision ID: 060
Revises: 059
Create Date: 2026-07-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "060"
down_revision: str | None = "059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_apikey",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_apikey", "revoked_at")
