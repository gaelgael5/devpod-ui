"""users, git_credentials, workspaces, workspace_extra_sources

Revision ID: 004
Revises: 003
Create Date: 2026-06-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("login", sa.Text, primary_key=True),
        sa.Column("version", sa.Text, nullable=False),
        sa.Column("secret_ns", UUID(as_uuid=False), nullable=False),
        sa.Column("default_ide", sa.Text, nullable=False, server_default="openvscode"),
        sa.Column("default_idle_timeout", sa.Text, nullable=False, server_default="4h"),
        sa.Column("harpocrate_api_key", sa.Text, nullable=False, server_default=""),
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
        sa.UniqueConstraint("secret_ns", name="uq_users_secret_ns"),
    )

    op.create_table(
        "git_credentials",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "login",
            sa.Text,
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("host", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("key_path", sa.Text, nullable=False, server_default=""),
        sa.Column("public_key", sa.Text, nullable=False, server_default=""),
        sa.Column("username", sa.Text, nullable=False, server_default=""),
        sa.Column("token", sa.Text, nullable=False, server_default=""),
        sa.UniqueConstraint("login", "name", name="uq_git_credentials_login_name"),
    )

    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "login",
            sa.Text,
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("branch", sa.Text, nullable=False, server_default=""),
        sa.Column("git_credential", sa.Text, nullable=False, server_default=""),
        sa.Column("host", sa.Text, nullable=False, server_default=""),
        sa.Column("template", sa.Text, nullable=False, server_default=""),
        sa.Column("devcontainer_path", sa.Text, nullable=False, server_default=""),
        sa.Column("recipes", ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("ide", sa.Text, nullable=False, server_default=""),
        sa.Column("idle_timeout", sa.Text, nullable=False, server_default=""),
        sa.Column("env", JSONB, nullable=False, server_default="{}"),
        sa.Column("expose_hostname", sa.Text, nullable=False, server_default=""),
        sa.Column("ssh_key", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("profile_scope", sa.Text, nullable=True),
        sa.Column("profile_slug", sa.Text, nullable=True),
        sa.Column("start_recipes", ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("default_start", sa.Text, nullable=False, server_default=""),
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
        sa.UniqueConstraint("login", "name", name="uq_workspaces_login_name"),
    )

    op.create_table(
        "workspace_extra_sources",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer,
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("branch", sa.Text, nullable=False, server_default=""),
        sa.Column("git_credential", sa.Text, nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("workspace_extra_sources")
    op.drop_table("workspaces")
    op.drop_table("git_credentials")
    op.drop_table("users")
