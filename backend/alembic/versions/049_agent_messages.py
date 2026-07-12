"""agent_messages : messagerie inter-agents à délivrance pilotée (spec 34).

Référence de workspace par ws_id texte ("{login}-{name}"), comme workspace_status —
workspaces.id (entier) est réattribué à chaque save de config, inutilisable en FK.

Revision ID: 049
Revises: 048
Create Date: 2026-07-05
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "049"
down_revision: str | None = "048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("owner_login", sa.Text(), nullable=False),
        sa.Column("from_ws_id", sa.Text(), nullable=False),
        sa.Column("from_session", sa.Text(), nullable=True),
        sa.Column("to_ws_id", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "reply_to",
            sa.Text(),
            sa.ForeignKey("agent_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_to_session", sa.Text(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("from_ws_id <> to_ws_id", name="ck_agent_messages_no_self"),
        sa.CheckConstraint(
            "char_length(subject) <= 200", name="ck_agent_messages_subject_len"
        ),
        sa.CheckConstraint("char_length(body) <= 20000", name="ck_agent_messages_body_len"),
        sa.CheckConstraint(
            "status IN ('pending', 'delivered', 'cancelled')", name="ck_agent_messages_status"
        ),
    )
    op.create_index(
        "idx_agent_messages_to_pending",
        "agent_messages",
        ["to_ws_id"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "idx_agent_messages_from", "agent_messages", ["from_ws_id", "created_at"]
    )
    op.create_index(
        "idx_agent_messages_reply_to",
        "agent_messages",
        ["reply_to"],
        postgresql_where=sa.text("reply_to IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("agent_messages")
