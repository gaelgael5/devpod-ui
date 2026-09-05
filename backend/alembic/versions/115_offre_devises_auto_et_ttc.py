"""Sens du prix, et devises derivees d'une majoration.

Trois colonnes sur `offers` :

- `prices_include_tax` : le montant saisi est-il TTC ou HT ? La reponse etait
  jusqu'ici DEDUITE du mode de taxe du canal. C'est fragile : une offre peut
  changer de canal sans que ses prix changent de nature, et l'administrateur
  doit pouvoir dire ce qu'il tape plutot que de le laisser inferer.

- `auto_currencies` + `currency_markup` : plutot que de ne rien proposer dans
  une devise sans prix propre, on derive le montant de celui de la devise par
  defaut. Le taux n'est PAS un taux de change — c'est une majoration
  commerciale, assumee comme telle. 1 = pas de majoration.

Revision ID: 115
Revises: 114
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "115"
down_revision: str | Sequence[str] | None = "114"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "offers",
        sa.Column("prices_include_tax", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "offers",
        sa.Column("auto_currencies", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "offers",
        sa.Column("currency_markup", sa.Numeric(7, 4), nullable=False, server_default="1"),
    )
    op.create_check_constraint("ck_offer_markup", "offers", "currency_markup > 0")


def downgrade() -> None:
    op.drop_constraint("ck_offer_markup", "offers", type_="check")
    for colonne in ("currency_markup", "auto_currencies", "prices_include_tax"):
        op.drop_column("offers", colonne)
