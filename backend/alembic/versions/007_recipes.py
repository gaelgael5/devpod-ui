"""Tour 7 : table recipes (métadonnées — scripts restent filesystem).

Revision ID: 007
Revises: 006
Create Date: 2026-06-17
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ARRAY

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recipes",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("login_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("scope", sa.Text(), nullable=False, server_default="shared"),
        sa.Column(
            "login",
            sa.Text(),
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False, server_default="install"),
        sa.Column("version", sa.Text(), nullable=False, server_default="1.0.0"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("options", JSONB(), nullable=False, server_default="{}"),
        sa.Column("requires_secrets", JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "installs_after",
            ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
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
        sa.PrimaryKeyConstraint("id", "scope", "login_key"),
    )
    op.create_index("idx_recipes_login", "recipes", ["login"], postgresql_where="login IS NOT NULL")
    op.create_index("idx_recipes_scope", "recipes", ["scope"])
    op.create_index("idx_recipes_type", "recipes", ["type"])


def downgrade() -> None:
    op.drop_index("idx_recipes_type", table_name="recipes")
    op.drop_index("idx_recipes_scope", table_name="recipes")
    op.drop_index("idx_recipes_login", table_name="recipes")
    op.drop_table("recipes")
