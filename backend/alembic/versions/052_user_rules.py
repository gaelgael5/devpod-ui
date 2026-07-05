"""user_rules : règles utilisateur du moteur sonde → condition → action.

Une règle réagit à un type d'événement applicatif ; la sonde et l'action sont
des outils MCP résolus via le profil du service référencé (user_services).
FK services en SET NULL : supprimer un service rend la règle inopérante (et
signalée dans l'UI) sans la faire disparaître.

Revision ID: 052
Revises: 051
Create Date: 2026-07-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "052"
down_revision: str | None = "051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
        sa.Column(
            "probe_service_id",
            sa.Text(),
            sa.ForeignKey("user_services.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("probe_tool", sa.Text(), nullable=False),
        sa.Column("probe_args", JSONB(), nullable=False, server_default="{}"),
        sa.Column("condition_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("condition_operator", sa.Text(), nullable=False),
        sa.Column("condition_value", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "action_service_id",
            sa.Text(),
            sa.ForeignKey("user_services.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action_tool", sa.Text(), nullable=False),
        sa.Column("action_args", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "condition_operator IN ('eq', 'neq', 'contains', 'not_contains')",
            name="ck_user_rules_operator",
        ),
    )
    op.create_index("idx_user_rules_owner_event", "user_rules", ["owner_login", "event_type"])


def downgrade() -> None:
    op.drop_table("user_rules")
