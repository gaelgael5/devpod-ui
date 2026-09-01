"""Ordre d'affichage des offres, decide par l'administrateur.

Les forfaits sortaient tries par `slug` : un ordre alphabetique, donc arbitraire
du point de vue commercial. L'offre gratuite se retrouvait a droite parce que son
slug commence par un `w`, et rien ne permettait de la deplacer.

`priorite` porte cet ordre. Croissante : 0 s'affiche en premier.

Defaut a 100 pour TOUTES les lignes existantes, y compris a la migration : le
parc garde ainsi exactement l'ordre qu'il avait — a priorite egale, `slug`
departage, ce qui est le tri actuel — jusqu'a ce que l'administrateur en decide
autrement. Une migration qui reordonnerait le catalogue toute seule serait une
surprise, pas un correctif.

Revision ID: 123
Revises: 122
Create Date: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "123"
down_revision: str | None = "122"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "offers",
        sa.Column("priorite", sa.Integer(), nullable=False, server_default="100"),
    )
    op.create_check_constraint("ck_offer_priorite", "offers", "priorite >= 0")


def downgrade() -> None:
    op.drop_constraint("ck_offer_priorite", "offers", type_="check")
    op.drop_column("offers", "priorite")
