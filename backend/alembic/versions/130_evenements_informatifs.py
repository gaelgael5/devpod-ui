"""Remboursements et litiges dans le journal des evenements d'abonnement.

Trois kinds s'ajoutent a la contrainte : `remboursement` (charge.refunded,
total ou partiel — le montant vit dans le payload), `litige_ouvert`
(charge.dispute.created, fonds geles) et `litige_clos`
(charge.dispute.closed, issue won/lost dans le payload).

Ils se JOURNALISENT sans transition d'etat : les trois arbitrages produit de la
fiche « Remboursements et litiges » (un remboursement coupe-t-il l'acces ? un
litige suspend-il ? quelle reaction a la cloture ?) sont encore ouverts. Un
litige invisible etait pire qu'un litige sans reaction — d'ou cette etape.

Revision ID: 130
Revises: 129
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "130"
down_revision: str | None = "129"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ANCIENS = "('debut_essai','activation','renouvellement','echec_paiement','resiliation')"
_NOUVEAUX = (
    "('debut_essai','activation','renouvellement','echec_paiement','resiliation',"
    "'remboursement','litige_ouvert','litige_clos')"
)


def upgrade() -> None:
    op.drop_constraint("ck_subscription_event_kind", "subscription_events", type_="check")
    op.create_check_constraint(
        "ck_subscription_event_kind", "subscription_events", f"kind IN {_NOUVEAUX}"
    )


def downgrade() -> None:
    op.drop_constraint("ck_subscription_event_kind", "subscription_events", type_="check")
    op.create_check_constraint(
        "ck_subscription_event_kind", "subscription_events", f"kind IN {_ANCIENS}"
    )
