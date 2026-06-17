"""node_join_tokens

Revision ID: 003
Revises: 002
Create Date: 2026-06-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "node_join_tokens",
        sa.Column("token_hash", sa.Text, primary_key=True),
        sa.Column("node_name", sa.Text, nullable=False),
        sa.Column("address", sa.Text, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_node_join_tokens_expires",
        "node_join_tokens",
        ["expires_at"],
        postgresql_where=sa.text("NOT used"),
    )


def downgrade() -> None:
    op.drop_index("idx_node_join_tokens_expires", table_name="node_join_tokens")
    op.drop_table("node_join_tokens")
