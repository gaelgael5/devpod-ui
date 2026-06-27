"""Tour 11 : table harpo_certificates.

Revision ID: 013
Revises: 012
Create Date: 2026-06-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "harpo_certificates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("cert_type", sa.Text(), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("private_key_local", sa.LargeBinary(), nullable=True),
        sa.Column("private_key_vault_ref", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("owner_login", "slug", name="uq_harpo_certs_login_slug"),
    )
    op.create_index("idx_harpo_certs_public", "harpo_certificates", ["is_public"])


def downgrade() -> None:
    op.drop_index("idx_harpo_certs_public", table_name="harpo_certificates")
    op.drop_table("harpo_certificates")
