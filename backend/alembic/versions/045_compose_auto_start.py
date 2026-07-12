"""compose_auto_start : préférence utilisateur de déploiement automatique.

Revision ID: 045
Revises: 044
Create Date: 2026-07-02
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "045"
down_revision: str | None = "044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "compose_auto_start",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "owner_login",
            sa.Text(),
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            sa.Text(),
            sa.ForeignKey("compose_template.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("env_values", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "owner_login", "template_id", name="uq_compose_auto_start_login_tpl"
        ),
    )


def downgrade() -> None:
    op.drop_table("compose_auto_start")
