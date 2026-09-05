"""Adresse de facturation chiffree : profil + instantane sur l'abonnement.

Deux emplacements, deux sens (fiche « Adresse de facturation au profil ») :

- `billing_addresses` : l'adresse COURANTE du compte, un blob chiffre cote
  serveur (KEK + HKDF, domaine `portal-billing-address` — PAS le coffre a PIN :
  le renouvellement doit la relire sans l'utilisateur). Aucune colonne en
  clair : rien d'interrogeable, rien qui fuite dans un dump.
- `subscriptions.billing_address_enc` : l'adresse FIGEE a la souscription.
  Un client qui demenage ne reecrit pas l'adresse de ses factures passees —
  meme doctrine que l'instantane de prix (`currency`/`amount_minor`).

Revision ID: 129
Revises: 128
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "129"
down_revision: str | None = "128"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "billing_addresses",
        sa.Column(
            "login",
            sa.Text(),
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("adresse_enc", sa.LargeBinary(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Nullable : les abonnements anterieurs a la colonne, et ceux souscrits
    # sans adresse au profil, n'en ont pas — le canal la demandera lui-meme.
    op.add_column(
        "subscriptions",
        sa.Column("billing_address_enc", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "billing_address_enc")
    op.drop_table("billing_addresses")
