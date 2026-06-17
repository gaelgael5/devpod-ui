"""Tour 8 : table workspace_ssh_keys + contrainte unique workspaces(login, name).

Revision ID: 008
Revises: 007
Create Date: 2026-06-17
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Contrainte UNIQUE nécessaire pour la FK composite dans workspace_ssh_keys
    op.create_unique_constraint("uq_workspaces_login_name", "workspaces", ["login", "name"])

    op.create_table(
        "workspace_ssh_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("login", sa.Text(), nullable=False),
        sa.Column("workspace_name", sa.Text(), nullable=False),
        sa.Column("private_key_path", sa.Text(), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["login", "workspace_name"],
            ["workspaces.login", "workspaces.name"],
            ondelete="CASCADE",
            name="fk_workspace_ssh_keys_workspace",
        ),
        sa.UniqueConstraint("login", "workspace_name", name="uq_workspace_ssh_keys_login_ws"),
    )


def downgrade() -> None:
    op.drop_table("workspace_ssh_keys")
    op.drop_constraint("uq_workspaces_login_name", "workspaces", type_="unique")
