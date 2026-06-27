"""Désactivation temporaire d'un service accordé (mcp_apikey_grant.enabled).

Revision ID: 026
Revises: 025
Create Date: 2026-06-25
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "026"
down_revision: str | None = "025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_apikey_grant",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("mcp_apikey_grant", "enabled")
