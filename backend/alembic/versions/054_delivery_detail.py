"""app_event_delivery.detail : détail structuré par livraison.

L'écouteur user-rules y journalise le résultat par règle déclenchée (verdict,
nombre d'actions, erreur éventuelle, arrêt d'enchaînement) — affiché dans
l'onglet Événements. Null pour les écouteurs qui ne fournissent pas de détail.

Revision ID: 054
Revises: 053
Create Date: 2026-07-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "054"
down_revision: str | None = "053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("app_event_delivery", sa.Column("detail", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("app_event_delivery", "detail")
