"""Kind `action_requise` dans le journal des evenements d'abonnement.

`invoice.payment_action_required` (Stripe) : un prelevement hors session bloque
par une authentification forte requise — le renouvellement a J+30 d'un
abonnement dont la carte n'a pas ete authentifiee au setup (fiche « SetupIntent
a l'inscription »). Journalise sans transition d'etat, comme les autres
evenements informatifs : ce n'est pas un echec definitif, et il ne doit pas
rester ignore en silence.

Revision ID: 131
Revises: 130
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "131"
down_revision: str | None = "130"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SANS = (
    "('debut_essai','activation','renouvellement','echec_paiement','resiliation',"
    "'remboursement','litige_ouvert','litige_clos')"
)
_AVEC = (
    "('debut_essai','activation','renouvellement','echec_paiement','resiliation',"
    "'remboursement','litige_ouvert','litige_clos','action_requise')"
)


def upgrade() -> None:
    op.drop_constraint("ck_subscription_event_kind", "subscription_events", type_="check")
    op.create_check_constraint(
        "ck_subscription_event_kind", "subscription_events", f"kind IN {_AVEC}"
    )


def downgrade() -> None:
    op.drop_constraint("ck_subscription_event_kind", "subscription_events", type_="check")
    op.create_check_constraint(
        "ck_subscription_event_kind", "subscription_events", f"kind IN {_SANS}"
    )
