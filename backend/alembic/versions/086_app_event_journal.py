"""Journal durable des events applicatifs (app_event) — fondation des automates.

Réintroduit une table `app_event`, mais en **journal durable à curseur** (et non
l'ancien moteur sonde→condition→action retiré en 074) : chaque event métier y est
appendé inconditionnellement à l'émission, `seq` (bigserial) donne l'ordre total
consommé par les automates locaux. Indépendant du producteur workflow.

Revision ID: 086
Revises: 085
Create Date: 2026-08-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "086"
down_revision: str | None = "085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_event",
        sa.Column("seq", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("workspace", sa.Text(), nullable=True),
        sa.Column("subject", JSONB(), nullable=False, server_default="{}"),
        sa.Column("correlation_id", sa.Text(), nullable=True),
        sa.Column("dedup_key", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_app_event_type", "app_event", ["event_type"])
    op.create_index("idx_app_event_workspace", "app_event", ["workspace"])


def downgrade() -> None:
    op.drop_index("idx_app_event_workspace", table_name="app_event")
    op.drop_index("idx_app_event_type", table_name="app_event")
    op.drop_table("app_event")
