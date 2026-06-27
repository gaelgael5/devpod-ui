"""harpo_secrets table.

Revision ID: 014
Revises: 013
Create Date: 2026-06-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "harpo_secrets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("secret_type", sa.Text(), nullable=False),
        sa.Column("secret_value_local", sa.LargeBinary(), nullable=True),
        sa.Column("secret_value_vault_ref", sa.Text(), nullable=True),
        sa.Column("storage_type", sa.Text(), nullable=False),
        sa.Column("vault_identifier", sa.Text(), nullable=True),
        sa.Column(
            "owner_login",
            sa.Text(),
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("owner_login", "slug", name="uq_harpo_secrets_login_slug"),
    )
    op.create_index("idx_harpo_secrets_type", "harpo_secrets", ["secret_type"])
    op.create_index("idx_harpo_secrets_public", "harpo_secrets", ["is_public"])


def downgrade() -> None:
    op.drop_index("idx_harpo_secrets_public", table_name="harpo_secrets")
    op.drop_index("idx_harpo_secrets_type", table_name="harpo_secrets")
    op.drop_table("harpo_secrets")
