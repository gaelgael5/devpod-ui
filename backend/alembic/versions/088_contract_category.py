"""Catégorie sur les contrats OpenAPI (tri/regroupement dans l'IHM).

Revision ID: 088
Revises: 087
Create Date: 2026-08-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "088"
down_revision: str | None = "087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "openapi_contract",
        sa.Column("category", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("openapi_contract", "category")
