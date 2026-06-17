"""profiles

Revision ID: 005
Revises: 004
Create Date: 2026-06-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("slug", sa.Text, nullable=False),
        sa.Column("scope", sa.Text, nullable=False),
        sa.Column("login_key", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "login",
            sa.Text,
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("extensions", ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("settings", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("slug", "scope", "login_key"),
    )
    op.create_index(
        "idx_profiles_login",
        "profiles",
        ["login"],
        postgresql_where=sa.text("login IS NOT NULL"),
    )
    op.create_index("idx_profiles_scope", "profiles", ["scope"])


def downgrade() -> None:
    op.drop_index("idx_profiles_scope", table_name="profiles")
    op.drop_index("idx_profiles_login", table_name="profiles")
    op.drop_table("profiles")
