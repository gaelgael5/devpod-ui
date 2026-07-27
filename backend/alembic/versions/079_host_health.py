"""host_health : état de vivacité des hosts posé par la sonde TCP périodique.

Enabler 727ee81d : `node_list` exposait health.reachable/last_seen à null faute
de probe. La sonde (nodes/liveness.py) persiste ici l'état courant — reachable
NULL = jamais sondé, last_seen = dernière sonde réussie, changed_at = entrée
dans l'état courant (transition, sert à l'alerte et à l'UI).

Revision ID: 079
Revises: 078
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "079"
down_revision: str | None = "078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "host_health",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("reachable", sa.Boolean(), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("host_health")
