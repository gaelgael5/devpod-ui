"""Socle des forfaits : pays, fiscalite, catalogue d'offres.

Cadrage du 27/08/2026 (backlog devpod, fiche « Admin — gestion des pays »).
Perimetre initial : la France seule, en mode de taxe `manuel`. Les Etats-Unis
reviendront en `automatique` (Stripe Tax) — le modele les porte deja, aucune
migration a prevoir pour ca.

Trois choix structurants, pour memoire :

- **Aucun secret ici.** `payment_providers.secret_slug` reference la table des
  secrets ; la cle API n'entre jamais dans cette table.
- **Les taux sont historises** (`valid_from`/`valid_to`), jamais ecrases : une
  facture emise l'an dernier doit rester reproductible avec le taux de l'epoque.
- **Les montants sont des entiers en unites mineures** (centimes). Un flottant
  sur de la facturation est une erreur silencieuse qui se decouvre au
  rapprochement bancaire.

Toutes les creations sont CONDITIONNELLES : une base deja deployee peut avoir vu
passer d'autres chemins de migration.

Revision ID: 110
Revises: 109
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "110"
down_revision: str | None = "109"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "offer_prices",
    "offers",
    "tax_rates",
    "country_providers",
    "country_currencies",
    "payment_providers",
    "countries",
)


def _existantes() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    presentes = _existantes()

    if "countries" not in presentes:
        op.create_table(
            "countries",
            sa.Column("code", sa.Text(), primary_key=True),
            sa.Column("label", sa.Text(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    if "payment_providers" not in presentes:
        op.create_table(
            "payment_providers",
            sa.Column("slug", sa.Text(), primary_key=True),
            # Discriminant d'adaptateur, distinct du slug : deux comptes Stripe
            # coexistent sans dupliquer le code qui les pilote.
            sa.Column("kind", sa.Text(), nullable=False),
            sa.Column("label", sa.Text(), nullable=False),
            sa.Column("tax_mode", sa.Text(), nullable=False, server_default="manuel"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("config", JSONB(), nullable=False, server_default="{}"),
            sa.Column("secret_slug", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "tax_mode IN ('automatique','manuel')", name="ck_provider_tax_mode"
            ),
        )

    if "country_currencies" not in presentes:
        op.create_table(
            "country_currencies",
            sa.Column(
                "country_code",
                sa.Text(),
                sa.ForeignKey("countries.code", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("currency", sa.Text(), nullable=False),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
            sa.UniqueConstraint("country_code", "currency", name="uq_country_currency"),
        )
        # Index partiel : une seule devise par defaut et par pays. Deux defauts
        # rendraient non deterministe le choix de devise a la souscription.
        op.create_index(
            "uq_country_currency_default",
            "country_currencies",
            ["country_code"],
            unique=True,
            postgresql_where=sa.text("is_default"),
        )

    if "country_providers" not in presentes:
        op.create_table(
            "country_providers",
            sa.Column(
                "country_code",
                sa.Text(),
                sa.ForeignKey("countries.code", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "provider_slug",
                sa.Text(),
                sa.ForeignKey("payment_providers.slug", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
            sa.UniqueConstraint("country_code", "provider_slug", name="uq_country_provider"),
        )

    if "tax_rates" not in presentes:
        op.create_table(
            "tax_rates",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column(
                "country_code",
                sa.Text(),
                sa.ForeignKey("countries.code", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("region", sa.Text(), nullable=False, server_default=""),
            sa.Column("rate", sa.Numeric(7, 4), nullable=False),
            sa.Column("label", sa.Text(), nullable=False),
            sa.Column("valid_from", sa.Date(), nullable=False),
            sa.Column("valid_to", sa.Date(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint("rate >= 0", name="ck_tax_rate_positive"),
            sa.CheckConstraint(
                "valid_to IS NULL OR valid_to > valid_from", name="ck_tax_rate_period"
            ),
        )
        op.create_index(
            "ix_tax_rates_lookup", "tax_rates", ["country_code", "region", "valid_from"]
        )

    if "offers" not in presentes:
        op.create_table(
            "offers",
            sa.Column("slug", sa.Text(), primary_key=True),
            sa.Column("labels", JSONB(), nullable=False, server_default="{}"),
            sa.Column("descriptions", JSONB(), nullable=False, server_default="{}"),
            sa.Column("hosting_type", sa.Text(), nullable=False, server_default="mutualise"),
            sa.Column("max_workspaces", sa.Integer(), nullable=True),
            sa.Column("max_hosts_dedies", sa.Integer(), nullable=True),
            sa.Column("variables", JSONB(), nullable=False, server_default="{}"),
            sa.Column(
                "provider_slug",
                sa.Text(),
                sa.ForeignKey("payment_providers.slug"),
                nullable=True,
            ),
            sa.Column("published", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "hosting_type IN ('dedie','mutualise')", name="ck_offer_hosting_type"
            ),
            sa.CheckConstraint(
                "max_workspaces IS NULL OR max_workspaces > 0", name="ck_offer_max_ws"
            ),
            sa.CheckConstraint(
                "max_hosts_dedies IS NULL OR max_hosts_dedies > 0", name="ck_offer_max_hosts"
            ),
        )

    if "offer_prices" not in presentes:
        op.create_table(
            "offer_prices",
            sa.Column(
                "offer_slug",
                sa.Text(),
                sa.ForeignKey("offers.slug", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("currency", sa.Text(), nullable=False),
            # Unites mineures : centimes, entier. Jamais un flottant.
            sa.Column("amount_minor", sa.BigInteger(), nullable=False),
            sa.Column("provider_price_id", sa.Text(), nullable=False, server_default=""),
            sa.UniqueConstraint("offer_slug", "currency", name="uq_offer_price_currency"),
            sa.CheckConstraint("amount_minor >= 0", name="ck_offer_price_positive"),
        )


def downgrade() -> None:
    presentes = _existantes()
    # Ordre inverse des dependances : les filles avant les meres.
    for nom in _TABLES:
        if nom in presentes:
            op.drop_table(nom)
