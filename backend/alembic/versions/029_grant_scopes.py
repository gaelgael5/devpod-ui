"""mcp_apikey_grant.scopes : scopes accordés (devpod). NULL = pas d'enforcement.

Revision ID: 029
Revises: 028
Create Date: 2026-06-26
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "029"
down_revision: str | None = "028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mcp_apikey_grant", sa.Column("scopes", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("mcp_apikey_grant", "scopes")
