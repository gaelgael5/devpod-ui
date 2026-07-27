"""Démontage de l'automatisation locale : app_event, app_event_delivery, user_rules, user_services.

Les onglets Services / Rules / Événements (moteur sonde → condition → action et son
journal) sont retirés : les events applicatifs sont désormais poussés vers workflow
via l'outbox transactionnel (`workflow_event_outbox`, conservé). On supprime les tables
locales dans l'ordre des FK : user_rules (self-ref next_rule_id) → user_services →
app_event_delivery (FK app_event) → app_event.

Revision ID: 074
Revises: 073
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "074"
down_revision: str | None = "073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("user_rules")
    op.drop_table("user_services")
    op.drop_table("app_event_delivery")
    op.drop_table("app_event")


def downgrade() -> None:
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
        sa.Column("detail", JSONB(), nullable=True),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("status IN ('ok', 'error')", name="ck_app_event_delivery_status"),
    )
    op.create_index("idx_app_event_delivery_event", "app_event_delivery", ["event_id"])

    op.create_table(
        "user_services",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "owner_login",
            sa.Text(),
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column(
            "mcp_profile_id",
            sa.Text(),
            sa.ForeignKey("mcp_profile.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "user_rules",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "owner_login",
            sa.Text(),
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("conditions", JSONB(), nullable=False, server_default="[]"),
        sa.Column("actions", JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "next_rule_id",
            sa.Text(),
            sa.ForeignKey("user_rules.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_user_rules_owner_event", "user_rules", ["owner_login", "event_type"])
