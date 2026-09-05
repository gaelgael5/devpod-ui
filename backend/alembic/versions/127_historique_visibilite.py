"""Visibilite d'une entree d'historique d'abonnement.

L'historique a UNE source — le journal `subscription_events` — et trois points
d'acces : la fiche admin d'un utilisateur (complet), la page globale admin
(complet), et l'onglet de l'utilisateur lui-meme (ses ACHATS uniquement). Le
filtre entre les trois est porte par l'entree, pas par trois requetes
divergentes : c'est le modele decide sur le ticket.

- **`achat`** (defaut) : l'entree concerne le compte en tant que client —
  souscription, activation, renouvellement, echec de paiement, resiliation.
  Tout ce que le journal contient aujourd'hui est de cette nature.
- **`operation`** : geste d'exploitation a tracer sans l'exposer au client —
  l'essai accorde par un administrateur, demain une reprise manuelle. Aucun
  ecrivain aujourd'hui : la colonne existe pour que ces entrees aient une place
  qui ne fuite pas cote client, pas pour l'inventer plus tard sous pression.

Revision ID: 127
Revises: 126
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "127"
down_revision: str | None = "126"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subscription_events",
        sa.Column("visibilite", sa.Text(), nullable=False, server_default="achat"),
    )
    op.create_check_constraint(
        "ck_subscription_event_visibilite",
        "subscription_events",
        "visibilite IN ('achat','operation')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_subscription_event_visibilite", "subscription_events", type_="check"
    )
    op.drop_column("subscription_events", "visibilite")
