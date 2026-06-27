"""hosts: ajout colonne usage (workspaces|tests) pour filtrer la sélection.

Revision ID: 020
Revises: 019
Create Date: 2026-06-24
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "020"
down_revision: str | None = "019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hosts",
        sa.Column(
            "usage",
            sa.Text(),
            nullable=False,
            server_default="workspaces",
        ),
    )


def downgrade() -> None:
    op.drop_column("hosts", "usage")
