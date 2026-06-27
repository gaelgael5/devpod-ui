"""Domaine DNS local pour la re-résolution d'IP (global_config.local_domain).

Revision ID: 024
Revises: 023
Create Date: 2026-06-25
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "024"
down_revision: str | None = "023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "global_config",
        sa.Column("local_domain", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("global_config", "local_domain")
