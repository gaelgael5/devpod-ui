"""OAuth client vers un backend MCP amont (ex. Confluence) — DCR, PKCE, par user.

La gateway devient CLIENT OAuth 2.1 d'un backend `auth_scheme="oauth"` :
- colonne `mcp_backend.oauth_auth_url` : URL du serveur d'autorisation si elle
  diffère de l'URL du MCP (vide = découverte auto) ;
- `mcp_backend_oauth_client` : client enregistré dynamiquement (DCR) + endpoints
  AS découverts, un par backend ;
- `mcp_backend_oauth_token` : access/refresh chiffrés KEK, par (backend, user) ;
- `mcp_backend_oauth_pending` : requête en vol (state anti-CSRF + verifier PKCE),
  TTL court, usage unique.

Revision ID: 084
Revises: 083
Create Date: 2026-08-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "084"
down_revision: str | None = "083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_backend",
        sa.Column("oauth_auth_url", sa.Text(), nullable=False, server_default=""),
    )

    op.create_table(
        "mcp_backend_oauth_client",
        sa.Column(
            "backend_id",
            sa.Text(),
            sa.ForeignKey("mcp_backend.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("authorization_endpoint", sa.Text(), nullable=False),
        sa.Column("token_endpoint", sa.Text(), nullable=False),
        sa.Column("registration_endpoint", sa.Text(), nullable=True),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("client_secret_enc", sa.LargeBinary(), nullable=True),
        sa.Column("scopes", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "mcp_backend_oauth_token",
        sa.Column(
            "backend_id",
            sa.Text(),
            sa.ForeignKey("mcp_backend.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_login",
            sa.Text(),
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("access_token_enc", sa.LargeBinary(), nullable=False),
        sa.Column("refresh_token_enc", sa.LargeBinary(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("backend_id", "user_login", name="uq_mcp_backend_oauth_token"),
    )

    op.create_table(
        "mcp_backend_oauth_pending",
        sa.Column("state", sa.Text(), primary_key=True),
        sa.Column(
            "backend_id",
            sa.Text(),
            sa.ForeignKey("mcp_backend.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_login",
            sa.Text(),
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_verifier", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("mcp_backend_oauth_pending")
    op.drop_table("mcp_backend_oauth_token")
    op.drop_table("mcp_backend_oauth_client")
    op.drop_column("mcp_backend", "oauth_auth_url")
