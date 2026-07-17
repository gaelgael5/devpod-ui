"""workspace_agent_sync : empreinte de la dernière config agents livrée par workspace.

Permet un resync idempotent : la réconciliation au boot / le resync à chaud ne
rotationnent les clefs MCP et ne réécrivent les fichiers que si l'empreinte a
changé — supprimant les ré-authentifications inutiles des agents workspace.

Revision ID: 072
Revises: 071
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "072"
down_revision: str | None = "071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_agent_sync",
        sa.Column("ws_id", sa.Text(), primary_key=True),
        sa.Column("config_hash", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("workspace_agent_sync")
