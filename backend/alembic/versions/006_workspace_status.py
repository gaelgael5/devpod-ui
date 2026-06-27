"""workspace_status

Revision ID: 006
Revises: 005
Create Date: 2026-06-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_status",
        sa.Column("ws_id", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("login", sa.Text, nullable=False, server_default=""),
        sa.Column("host_port", sa.Integer, nullable=True),
        sa.Column("host_type", sa.Text, nullable=True),
        sa.Column("host_name", sa.Text, nullable=True),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column("hostname", sa.Text, nullable=True),
        sa.Column("returncode", sa.Integer, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("ws_id"),
    )
    op.create_index("idx_workspace_status_login", "workspace_status", ["login"])
    op.create_index("idx_workspace_status_status", "workspace_status", ["status"])


def downgrade() -> None:
    op.drop_index("idx_workspace_status_status", table_name="workspace_status")
    op.drop_index("idx_workspace_status_login", table_name="workspace_status")
    op.drop_table("workspace_status")
