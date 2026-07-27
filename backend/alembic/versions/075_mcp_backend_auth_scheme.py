"""mcp_backend.auth_scheme : schéma d'authentification par backend MCP.

"bearer" (défaut, comportement historique : Authorization: Bearer <clé>, standard
MCP) ou "x_api_key" (X-API-Key: <clé>) pour les serveurs non conformes qui exigent
ce header — ex. la gateway MCP d'agflow (workflow.yoops.org) qui répond
"Valid X-API-Key required" sinon. Cf. mcp/connections.open_session.

Revision ID: 075
Revises: 074
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "075"
down_revision: str | None = "074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_backend",
        sa.Column("auth_scheme", sa.Text(), nullable=False, server_default="bearer"),
    )


def downgrade() -> None:
    op.drop_column("mcp_backend", "auth_scheme")
