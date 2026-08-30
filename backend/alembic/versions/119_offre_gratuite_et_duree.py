"""Gratuite d'une offre, duree du forfait, et jour d'arret d'un abonnement.

Un forfait est soit un forfait de BIENVENUE — gratuit, pour essayer le produit
— soit un forfait PAYANT. Les deux sont bornes dans le temps : l'essai parce
qu'il doit finir, le payant parce qu'un abonnement sans terme ne se facture pas.

`is_free` est un drapeau, et non l'absence de prix. Les deux se confondraient
autrement : une offre payante dont on a oublie le prix est une erreur de
saisie, pas une offre gratuite — et publier la premiere doit rester impossible
quand publier la seconde est normal.

`duration_days` reste NULL tant qu'elle n'est pas renseignee : l'offre est
alors un brouillon. C'est la PUBLICATION qui l'exige, comme elle exige deja un
prix dans une devise activee — meme garde-fou, meme endroit.

`subscriptions.ends_at` porte le jour d'arret, calcule a la souscription. Il ne
remplace pas `current_period_end`, qui est la fin de la periode facturee cote
fournisseur : celle-la se renouvelle, celui-ci arrete le service.

Revision ID: 119
Revises: 118
Create Date: 2026-08-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "119"
down_revision: str | Sequence[str] | None = "118"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "offers", sa.Column("is_free", sa.Boolean(), nullable=False, server_default="false")
    )
    op.add_column("offers", sa.Column("duration_days", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_offer_duration", "offers", "duration_days IS NULL OR duration_days > 0"
    )
    op.add_column("subscriptions", sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("subscriptions", "ends_at")
    op.drop_constraint("ck_offer_duration", "offers", type_="check")
    op.drop_column("offers", "duration_days")
    op.drop_column("offers", "is_free")
