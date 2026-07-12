"""test_host_links : liens (clé → URL) attachés à un serveur de test.

Affichés dans le menu ⋮ du host (vue workspace) ; supprimés en cascade avec
l'association workspace_test_hosts quand la VM de test est détruite.

Revision ID: 047
Revises: 046
Create Date: 2026-07-04
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "047"
down_revision: str | None = "046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "test_host_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "test_host_id",
            sa.Integer(),
            sa.ForeignKey("workspace_test_hosts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("test_host_id", "key", name="uq_thl_host_key"),
    )


def downgrade() -> None:
    op.drop_table("test_host_links")
