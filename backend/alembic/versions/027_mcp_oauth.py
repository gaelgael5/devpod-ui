"""Authorization Server OAuth de la passerelle MCP : clients, codes, colonnes apikey.

Revision ID: 027
Revises: 026
Create Date: 2026-06-26
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "027"
down_revision: str | None = "026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_oauth_client",
        sa.Column("client_id", sa.Text(), primary_key=True),
        sa.Column("redirect_uris", JSONB(), nullable=False, server_default="[]"),
        sa.Column("client_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("client_metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "mcp_oauth_authcode",
        sa.Column("code_hash", sa.Text(), primary_key=True),
        sa.Column(
            "client_id",
            sa.Text(),
            sa.ForeignKey("mcp_oauth_client.client_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_login",
            sa.Text(),
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False, server_default=""),
        sa.Column("grants", JSONB(), nullable=False, server_default="[]"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "mcp_apikey", sa.Column("kind", sa.Text(), nullable=False, server_default="apikey")
    )
    op.add_column("mcp_apikey", sa.Column("client_id", sa.Text(), nullable=True))
    op.add_column("mcp_apikey", sa.Column("refresh_token_hash", sa.Text(), nullable=True))
    op.add_column("mcp_apikey", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("mcp_apikey", "expires_at")
    op.drop_column("mcp_apikey", "refresh_token_hash")
    op.drop_column("mcp_apikey", "client_id")
    op.drop_column("mcp_apikey", "kind")
    op.drop_table("mcp_oauth_authcode")
    op.drop_table("mcp_oauth_client")
