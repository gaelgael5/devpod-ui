"""Phase 2 : tables user_pin_config et user_harpocrate_keys.

Revision ID: 011
Revises: 010
Create Date: 2026-06-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_pin_config",
        sa.Column("login", sa.Text(), primary_key=True),
        sa.Column("encrypted_master_key", sa.LargeBinary(), nullable=False),
        sa.Column("pin_salt", sa.LargeBinary(), nullable=False),
        sa.Column("encrypted_master_key_recovery", sa.LargeBinary(), nullable=False),
        sa.Column("recovery_salt", sa.LargeBinary(), nullable=False),
        sa.Column("pin_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["login"], ["users.login"], ondelete="CASCADE"),
    )
    op.create_table(
        "user_harpocrate_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("login", sa.Text(), nullable=False),
        sa.Column("identifier", sa.Text(), nullable=False),
        sa.Column("encrypted_token", sa.LargeBinary(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["login"], ["users.login"], ondelete="CASCADE"),
        sa.UniqueConstraint("login", "identifier", name="uq_user_harpocrate_keys_login_id"),
    )


def downgrade() -> None:
    op.drop_table("user_harpocrate_keys")
    op.drop_table("user_pin_config")
