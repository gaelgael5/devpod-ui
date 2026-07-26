"""Suggestion d'arrêt des workspaces inactifs (enabler 6016436b).

- `workspaces.keep_active` : épingle « garder actif » — exempte le workspace de
  toute suggestion d'arrêt, quel que soit son idle.
- `workspace_idle` : période d'inactivité continue observée par la sonde
  (sessions/idle.py). Une ligne = un workspace actuellement inactif ; supprimée
  dès qu'une activité reprend. `alerted_at` non nul = alerte déjà émise pour
  cette période (une seule alerte par période d'inactivité continue).

Revision ID: 080
Revises: 079
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "080"
down_revision: str | None = "079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("keep_active", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_table(
        "workspace_idle",
        sa.Column("ws_id", sa.Text(), primary_key=True),
        sa.Column("login", sa.Text(), nullable=False),
        sa.Column("idle_since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("workspace_idle")
    op.drop_column("workspaces", "keep_active")
