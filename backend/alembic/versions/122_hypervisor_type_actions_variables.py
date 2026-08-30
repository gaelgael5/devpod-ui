"""hypervisor_types : persistance des actions et des variables declarees.

Les deux listes existaient dans le modele pydantic, transitaient par l'API et
etaient servies par le cache memoire de la configuration globale — mais aucune
colonne ne les portait. Elles disparaissaient donc au premier rechargement
depuis la base (redemarrage du portail), sans erreur ni trace.

`server_default='[]'` : les lignes anterieures a cette migration se relisent en
listes vides, ce qui est exactement leur etat reel.

Revision ID: 122
Revises: 121
Create Date: 2026-08-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "122"
down_revision: str | None = "121"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hypervisor_types",
        sa.Column("actions", JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "hypervisor_types",
        sa.Column("variables", JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("hypervisor_types", "variables")
    op.drop_column("hypervisor_types", "actions")
