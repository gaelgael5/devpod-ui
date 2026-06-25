"""Alias testN pour les machines de test (workspace_test_hosts.alias).

Revision ID: 023
Revises: 022
Create Date: 2026-06-25
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "023"
down_revision: str | None = "022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspace_test_hosts",
        sa.Column("alias", sa.Text(), nullable=True),
    )
    # Backfill : numérote testN par (login, workspace) dans l'ordre de création.
    op.execute(
        """
        UPDATE workspace_test_hosts AS w
        SET alias = 'test' || sub.rn
        FROM (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY login, workspace_name
                       ORDER BY created_at, id
                   ) AS rn
            FROM workspace_test_hosts
        ) AS sub
        WHERE w.id = sub.id
        """
    )


def downgrade() -> None:
    op.drop_column("workspace_test_hosts", "alias")
