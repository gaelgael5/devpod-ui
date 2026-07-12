"""mcp_backend.quarantine_disabled : opt-out de la protection par quarantaine.

La détection de redéfinition (anti rug-pull, spec 23) reste active par défaut.
Pour les backends de confiance (services exposés par l'utilisateur lui-même),
ce flag désactive la mise en quarantaine : le catalogue converge toujours vers
le tools/list du backend et une quarantaine héritée est levée au resync.

Revision ID: 055
Revises: 054
Create Date: 2026-07-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "055"
down_revision: str | None = "054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_backend",
        sa.Column("quarantine_disabled", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("mcp_backend", "quarantine_disabled")
