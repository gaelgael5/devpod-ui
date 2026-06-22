"""mcp gateway lot 1 : backends, clés de service, apikeys clients, grants.

Revision ID: 017
Revises: 016
Create Date: 2026-06-22
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "017"
down_revision: str | None = "016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_backend",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "owner_login",
            sa.Text(),
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("transport", sa.Text(), nullable=False, server_default="streamable_http"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
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
        sa.UniqueConstraint("owner_login", "namespace", name="uq_mcp_backend_owner_namespace"),
    )
    op.create_table(
        "mcp_backend_key",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "backend_id",
            sa.Text(),
            sa.ForeignKey("mcp_backend.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("storage_type", sa.Text(), nullable=False),
        sa.Column("secret_value_local", sa.LargeBinary(), nullable=True),
        sa.Column("secret_value_vault_ref", sa.Text(), nullable=True),
        sa.Column("vault_identifier", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("backend_id", "slug", name="uq_mcp_backend_key_backend_slug"),
    )
    op.create_table(
        "mcp_apikey",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "owner_login",
            sa.Text(),
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False, server_default=""),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "mcp_apikey_grant",
        sa.Column(
            "apikey_id",
            sa.Text(),
            sa.ForeignKey("mcp_apikey.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "backend_id",
            sa.Text(),
            sa.ForeignKey("mcp_backend.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "backend_key_id",
            sa.Text(),
            sa.ForeignKey("mcp_backend_key.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("apikey_id", "backend_id", name="pk_mcp_apikey_grant"),
    )


def downgrade() -> None:
    op.drop_table("mcp_apikey_grant")
    op.drop_table("mcp_apikey")
    op.drop_table("mcp_backend_key")
    op.drop_table("mcp_backend")
