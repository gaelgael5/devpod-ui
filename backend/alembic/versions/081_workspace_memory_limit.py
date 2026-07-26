"""workspaces.memory_limit : surcharge de la limite mémoire du conteneur.

Enabler 59864c37 (robustesse mémoire) : le devcontainer généré porte
`runArgs: ["--memory=…"]` — un agent emballé tue SON conteneur au lieu de faire
tomber le host (l'OOM du 23/07 avait tué networkd). Le défaut vit dans la config
globale (`devpod.defaults.memory_limit`) ; cette colonne est la surcharge
ponctuelle par workspace ("" = hériter).

Revision ID: 081
Revises: 080
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "081"
down_revision: str | None = "080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("memory_limit", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "memory_limit")
