"""Ajoute profile_id sur mcp_oauth_authcode pour lier le consentement OAuth à un profil MCP.

Revision ID: 039
Revises: 038
Create Date: 2026-06-29
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "039"
down_revision: str | None = "038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mcp_oauth_authcode", sa.Column("profile_id", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("mcp_oauth_authcode", "profile_id")
