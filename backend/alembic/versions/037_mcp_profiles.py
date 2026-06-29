"""MCP profiles — remplace mcp_apikey_grant par mcp_profile + mcp_profile_entry

Revision ID: 037
Revises: 036
Create Date: 2026-06-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Profils ──────────────────────────────────────────────────────────────
    op.create_table(
        "mcp_profile",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "owner_login",
            sa.Text,
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "mcp_profile_entry",
        sa.Column(
            "profile_id",
            sa.Text,
            sa.ForeignKey("mcp_profile.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "backend_id",
            sa.Text,
            sa.ForeignKey("mcp_backend.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "backend_key_id",
            sa.Text,
            sa.ForeignKey("mcp_backend_key.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tools", JSONB, nullable=True),
        sa.UniqueConstraint("profile_id", "backend_id", name="uq_mcp_profile_entry"),
    )

    # ── mcp_apikey : ajout profile_id ────────────────────────────────────────
    op.add_column(
        "mcp_apikey",
        sa.Column(
            "profile_id",
            sa.Text,
            sa.ForeignKey("mcp_profile.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # ── Suppression des grants ────────────────────────────────────────────────
    op.drop_table("mcp_apikey_grant")


def downgrade() -> None:
    op.add_column("mcp_apikey", sa.Column("profile_id", sa.Text, nullable=True))

    op.create_table(
        "mcp_apikey_grant",
        sa.Column(
            "apikey_id",
            sa.Text,
            sa.ForeignKey("mcp_apikey.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "backend_id",
            sa.Text,
            sa.ForeignKey("mcp_backend.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "backend_key_id",
            sa.Text,
            sa.ForeignKey("mcp_backend_key.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("expose_mode", sa.Text, nullable=False, server_default="all"),
        sa.Column("expose", JSONB, nullable=False, server_default="[]"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("scopes", JSONB, nullable=True),
        sa.UniqueConstraint("apikey_id", "backend_id", name="uq_mcp_apikey_grant_apikey_backend"),
    )

    op.drop_column("mcp_apikey", "profile_id")
    op.drop_table("mcp_profile_entry")
    op.drop_table("mcp_profile")
