"""Provenance d'une recette importee : URL de son manifeste distant.

Sans elle, une recette installee est coupee de son origine : impossible de dire
si la version publiee a bouge, ni de la remettre a jour autrement qu'en la
supprimant et en la reimportant. La colonne est vide pour une recette creee a la
main ou livree avec le produit — seul un import distant la renseigne.

Ajout CONDITIONNEL : une base deja deployee peut avoir vu passer d'autres
chemins de migration.

Revision ID: 109
Revises: 108
Create Date: 2026-08-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "109"
down_revision: str | None = "108"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "recipes"
_COL = "source_url"


def _colonnes() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {c["name"] for c in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    if _COL not in _colonnes():
        op.add_column(_TABLE, sa.Column(_COL, sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    if _COL in _colonnes():
        op.drop_column(_TABLE, _COL)
