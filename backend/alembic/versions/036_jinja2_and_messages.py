"""Système de messages contextuels pour agents : templates Jinja2 + messages workspace.

Revision ID: 036
Revises: 035
Create Date: 2026-06-29
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "036"
down_revision: str | None = "035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Nouvelles tables ──────────────────────────────────────────────────────
    op.create_table(
        "jinja2_template",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("culture", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("key", "culture", name="pk_jinja2_template"),
    )
    op.create_index("idx_jinja2_template_key", "jinja2_template", ["key"])

    op.create_table(
        "workspace_message",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("owner_login", sa.Text(), nullable=False),
        sa.Column("workspace_name", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_workspace_message_ws",
        "workspace_message",
        ["owner_login", "workspace_name", "created_at"],
    )

    # ── Colonnes sur tables existantes ────────────────────────────────────────
    op.add_column("users", sa.Column("culture", sa.Text(), nullable=False, server_default="fr"))

    op.add_column("compose_template", sa.Column("message_key", sa.Text(), nullable=True))

    op.add_column(
        "workspace_test_hosts",
        sa.Column(
            "message_id",
            sa.BigInteger(),
            sa.ForeignKey("workspace_message.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.add_column(
        "compose_deployment",
        sa.Column(
            "message_id",
            sa.BigInteger(),
            sa.ForeignKey("workspace_message.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("compose_deployment", "message_id")
    op.drop_column("workspace_test_hosts", "message_id")
    op.drop_column("compose_template", "message_key")
    op.drop_column("users", "culture")
    op.drop_index("idx_workspace_message_ws", table_name="workspace_message")
    op.drop_table("workspace_message")
    op.drop_index("idx_jinja2_template_key", table_name="jinja2_template")
    op.drop_table("jinja2_template")
