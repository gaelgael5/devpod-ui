"""Tour 9 : table workspace_log_blobs (logs complets par opération).

Revision ID: 009
Revises: 008
Create Date: 2026-06-17
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_log_blobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ws_id", sa.Text(), nullable=False),
        sa.Column("login", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False, server_default="up"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("ws_id", "operation", "started_at", name="uq_workspace_log_blobs"),
    )
    op.create_index("idx_workspace_log_blobs_ws_id", "workspace_log_blobs", ["ws_id"])
    op.create_index(
        "idx_workspace_log_blobs_login", "workspace_log_blobs", ["login"]
    )


def downgrade() -> None:
    op.drop_index("idx_workspace_log_blobs_login", table_name="workspace_log_blobs")
    op.drop_index("idx_workspace_log_blobs_ws_id", table_name="workspace_log_blobs")
    op.drop_table("workspace_log_blobs")
