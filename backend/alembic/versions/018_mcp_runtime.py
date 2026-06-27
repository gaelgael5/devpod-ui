"""mcp runtime : catalogue, audit, curation par grant.

Revision ID: 018
Revises: 017
Create Date: 2026-06-22
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "018"
down_revision: str | None = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_tool_catalog",
        sa.Column(
            "backend_id",
            sa.Text(),
            sa.ForeignKey("mcp_backend.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("original_name", sa.Text(), nullable=False),
        sa.Column("definition", JSONB(), nullable=False),
        sa.Column("definition_hash", sa.Text(), nullable=False),
        sa.Column(
            "first_seen",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("quarantined", sa.Boolean(), nullable=False, server_default="false"),
        sa.UniqueConstraint(
            "backend_id", "kind", "original_name", name="pk_mcp_tool_catalog"
        ),
    )
    op.create_table(
        "mcp_audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("apikey_id", sa.Text(), nullable=True),
        sa.Column("owner_login", sa.Text(), nullable=True),
        sa.Column("namespaced_name", sa.Text(), nullable=True),
        sa.Column("backend_id", sa.Text(), nullable=True),
        sa.Column("backend_key_id", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.add_column(
        "mcp_apikey_grant",
        sa.Column("expose_mode", sa.Text(), nullable=False, server_default="all"),
    )
    op.add_column(
        "mcp_apikey_grant",
        sa.Column("expose", JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("mcp_apikey_grant", "expose")
    op.drop_column("mcp_apikey_grant", "expose_mode")
    op.drop_table("mcp_audit_log")
    op.drop_table("mcp_tool_catalog")
