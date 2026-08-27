"""Abonnements, idempotence des webhooks, et propriete des machines.

Suite du socle 110. Trois mecanismes, chacun avec une raison d'etre precise :

- **`subscriptions`** distingue la RESILIATION de la SUPPRESSION DE COMPTE :
  `resilie` est un etat clos et reversible — le compte demeure, une reprise
  rouvre l'abonnement au tarif du jour. La suppression de compte, elle, est
  definitive : elle efface la ligne `users` et emporte les abonnements en
  `ON DELETE CASCADE`. Ce n'est pas un etat d'abonnement.
- **`subscriptions`** porte un INSTANTANE du prix (`currency` + `amount_minor`)
  et non une jointure vers `offer_prices` : le catalogue evolue, un abonne garde
  le prix auquel il a souscrit, et une facture ancienne reste reproductible.
- **`subscription_events`** est a la fois l'historique et le MAGASIN
  D'IDEMPOTENCE des webhooks. `(provider_slug, provider_event_id)` est unique :
  les fournisseurs de paiement rejouent leurs notifications (c'est leur
  fonctionnement nominal, pas un incident), et sans cette contrainte un renvoi
  provisionnerait ou facturerait deux fois.
- **`host_ownership` / `host_guests`** portent la propriete d'une machine dediee
  et ses invites, avec DEUX plafonds dont l'ordre n'est pas negociable :
  `capacity_workspaces` est ce que la machine supporte sans planter — limite
  physique, elle prime sur tout —, `offer_max_workspaces` est le quota du
  forfait, qui peut etre plus bas mais jamais la relever. C'est une capacite de
  MACHINE, partagee entre l'owner et ses invites.

Creations conditionnelles, comme en 110.

Revision ID: 111
Revises: 110
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "111"
down_revision: str | None = "110"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("host_guests", "host_ownership", "subscription_events", "subscriptions")


def _existantes() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _horodatage(nom: str) -> sa.Column:
    return sa.Column(nom, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    presentes = _existantes()

    if "subscriptions" not in presentes:
        op.create_table(
            "subscriptions",
            sa.Column("id", UUID(as_uuid=False), primary_key=True),
            sa.Column(
                "login",
                sa.Text(),
                sa.ForeignKey("users.login", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("offer_slug", sa.Text(), sa.ForeignKey("offers.slug"), nullable=False),
            sa.Column(
                "provider_slug",
                sa.Text(),
                sa.ForeignKey("payment_providers.slug"),
                nullable=True,
            ),
            sa.Column("state", sa.Text(), nullable=False, server_default="essai"),
            sa.Column("country_code", sa.Text(), nullable=False),
            # Instantane du prix a la souscription (cf. entete).
            sa.Column("currency", sa.Text(), nullable=False),
            sa.Column("amount_minor", sa.BigInteger(), nullable=False),
            sa.Column("provider_subscription_id", sa.Text(), nullable=False, server_default=""),
            # Relance : on ne coupe pas au premier refus (souvent passager), on
            # relance une fois au bout du delai configure, puis on resilie.
            sa.Column("payment_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("trial_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
            # Point de depart du delai de retention calcule par le scheduler.
            _horodatage("state_changed_at"),
            _horodatage("created_at"),
            _horodatage("updated_at"),
            sa.CheckConstraint(
                "state IN ('essai','actif','echec_paiement','resilie')",
                name="ck_subscription_state",
            ),
            sa.CheckConstraint("amount_minor >= 0", name="ck_subscription_amount"),
            sa.CheckConstraint("payment_attempts >= 0", name="ck_subscription_attempts"),
        )
        op.create_index("ix_subscriptions_login", "subscriptions", ["login"])
        op.create_index("ix_subscriptions_state", "subscriptions", ["state", "state_changed_at"])
        # Le scheduler demande « qui est du maintenant ? » : index partiel, pour
        # ne pas balayer les abonnements sains a chaque tick.
        op.create_index(
            "ix_subscriptions_retry",
            "subscriptions",
            ["next_retry_at"],
            postgresql_where=sa.text("next_retry_at IS NOT NULL"),
        )

    if "subscription_events" not in presentes:
        op.create_table(
            "subscription_events",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column(
                "subscription_id",
                UUID(as_uuid=False),
                sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("login", sa.Text(), nullable=False, server_default=""),
            sa.Column("kind", sa.Text(), nullable=False),
            sa.Column("provider_slug", sa.Text(), nullable=False),
            sa.Column("provider_event_id", sa.Text(), nullable=False),
            sa.Column("payload", JSONB(), nullable=False, server_default="{}"),
            _horodatage("occurred_at"),
            _horodatage("created_at"),
            # Clef d'idempotence : c'est elle qui rend un webhook rejouable.
            sa.UniqueConstraint(
                "provider_slug", "provider_event_id", name="uq_subscription_event_provider"
            ),
            sa.CheckConstraint(
                "kind IN ('debut_essai','activation','renouvellement',"
                "'echec_paiement','resiliation')",
                name="ck_subscription_event_kind",
            ),
        )
        op.create_index("ix_subscription_events_sub", "subscription_events", ["subscription_id"])

    if "host_ownership" not in presentes:
        op.create_table(
            "host_ownership",
            sa.Column(
                "host_name",
                sa.Text(),
                sa.ForeignKey("hosts.name", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "owner_login",
                sa.Text(),
                sa.ForeignKey("users.login", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("hosting_type", sa.Text(), nullable=False, server_default="dedie"),
            sa.Column("offer_slug", sa.Text(), nullable=True),
            # Deux plafonds. `capacity_workspaces` = ce que la MACHINE supporte
            # sans planter : limite physique, elle prime sur tout. Le quota du
            # forfait peut etre plus bas, jamais la relever. NULL = pas de
            # plafond de ce cote-la.
            sa.Column("capacity_workspaces", sa.Integer(), nullable=True),
            sa.Column("offer_max_workspaces", sa.Integer(), nullable=True),
            _horodatage("created_at"),
            sa.CheckConstraint(
                "hosting_type IN ('dedie','mutualise')", name="ck_ownership_hosting_type"
            ),
            sa.CheckConstraint(
                "capacity_workspaces IS NULL OR capacity_workspaces >= 0",
                name="ck_ownership_capacity",
            ),
        )
        op.create_index("ix_host_ownership_owner", "host_ownership", ["owner_login"])

    if "host_guests" not in presentes:
        op.create_table(
            "host_guests",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column(
                "host_name",
                sa.Text(),
                sa.ForeignKey("hosts.name", ondelete="CASCADE"),
                nullable=False,
            ),
            # On invite une ADRESSE : le compte peut ne pas exister encore, d'ou
            # `login` nullable jusqu'a l'acceptation.
            sa.Column("email", sa.Text(), nullable=False),
            sa.Column(
                "login", sa.Text(), sa.ForeignKey("users.login", ondelete="SET NULL"), nullable=True
            ),
            sa.Column("allocated_workspaces", sa.Integer(), nullable=True),
            sa.Column("state", sa.Text(), nullable=False, server_default="invite"),
            sa.Column("token", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            _horodatage("created_at"),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("host_name", "email", name="uq_host_guest_email"),
            sa.UniqueConstraint("token", name="uq_host_guest_token"),
            sa.CheckConstraint(
                "state IN ('invite','accepte','revoque')", name="ck_host_guest_state"
            ),
            sa.CheckConstraint(
                "allocated_workspaces IS NULL OR allocated_workspaces > 0",
                name="ck_host_guest_alloc",
            ),
        )
        op.create_index("ix_host_guests_login", "host_guests", ["login"])


def downgrade() -> None:
    presentes = _existantes()
    for nom in _TABLES:
        if nom in presentes:
            op.drop_table(nom)
