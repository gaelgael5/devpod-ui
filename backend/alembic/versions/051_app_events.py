"""app_event + app_event_delivery : journal du bus d'événements applicatifs.

Un événement est un fait accompli émis par la couche service (workspace créé,
session tmux ouverte, service compose démarré…). Chaque livraison à un écouteur
est tracée (ok/error) — un échec d'écouteur est visible et rejouable, jamais
avalé. `actor` sans FK vers users : le journal survit à la purge d'un compte.

Revision ID: 051
Revises: 050
Create Date: 2026-07-05
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "051"
down_revision: str | None = "050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_event",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("workspace", sa.Text(), nullable=True),
        sa.Column("subject", JSONB(), nullable=False, server_default="{}"),
        sa.Column("correlation_id", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_app_event_actor_time", "app_event", ["actor", "occurred_at"])

    op.create_table(
        "app_event_delivery",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "event_id",
            sa.Text(),
            sa.ForeignKey("app_event.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("listener", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("status IN ('ok', 'error')", name="ck_app_event_delivery_status"),
    )
    op.create_index("idx_app_event_delivery_event", "app_event_delivery", ["event_id"])


def downgrade() -> None:
    op.drop_table("app_event_delivery")
    op.drop_table("app_event")
