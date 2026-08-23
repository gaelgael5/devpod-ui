"""Onglet Filtre : configuration d'un appel d'API préliminaire sur l'automate.

Persiste un appel de filtrage (ex. « l'utilisateur existe-t-il ? » via
GET /users/list) dont l'IHM affiche le payload. L'ÉVALUATION du résultat est
différée : ces colonnes ne décrivent que l'appel, pas la condition.

Revision ID: 091
Revises: 090
Create Date: 2026-08-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "091"
down_revision: str | None = "090"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "automation",
        sa.Column(
            "filter_contract_ref",
            sa.Text(),
            sa.ForeignKey("openapi_contract.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("automation", sa.Column("filter_operation_id", sa.Text(), nullable=True))
    op.add_column("automation", sa.Column("filter_url", sa.Text(), nullable=True))
    op.add_column("automation", sa.Column("filter_method", sa.Text(), nullable=True))
    op.add_column("automation", sa.Column("filter_body", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("automation", "filter_body")
    op.drop_column("automation", "filter_method")
    op.drop_column("automation", "filter_url")
    op.drop_column("automation", "filter_operation_id")
    op.drop_column("automation", "filter_contract_ref")
