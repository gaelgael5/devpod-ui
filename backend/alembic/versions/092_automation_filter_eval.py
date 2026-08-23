"""Évaluation du filtre : JSONPath + opérateur + valeur attendue sur l'automate.

Complète les colonnes d'appel de filtre (091) par la règle d'évaluation : le
runner gate l'appel principal sur `filter_operator` appliqué au JSONPath
`filter_jsonpath` (variables rendues) de la réponse, comparé à `filter_expected`.

Revision ID: 092
Revises: 091
Create Date: 2026-08-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "092"
down_revision: str | None = "091"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("automation", sa.Column("filter_jsonpath", sa.Text(), nullable=True))
    op.add_column("automation", sa.Column("filter_operator", sa.Text(), nullable=True))
    op.add_column("automation", sa.Column("filter_expected", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("automation", "filter_expected")
    op.drop_column("automation", "filter_operator")
    op.drop_column("automation", "filter_jsonpath")
