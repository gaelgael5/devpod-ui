"""Les événements applicatifs du cycle d'abonnement.

Ce que ces tests verrouillent : la table kind → type est exhaustive (un kind
ajouté sans décider de son événement est une erreur détectée, pas un silence),
le payload est celui DÉCIDÉ par la fiche « Automate — événements user
(forfait) », et l'émission ne casse jamais la transition qui la précède.
"""

from __future__ import annotations

from typing import Any, get_args

import pytest

import portal.db.billing_offers as db_offers
import portal.db.user_config as db_user
import portal.events.bus as bus
from portal.billing.evenements import (
    TYPE_PAR_KIND,
    TYPE_RETENTION_EXPIREE,
    publier_evenement_abonnement,
)
from portal.billing.models import Offer
from portal.billing.subscriptions import EventKind, Subscription
from portal.events.models import EVENT_TYPES


def _abonnement(**extra: Any) -> Subscription:
    base: dict[str, Any] = {
        "id": "00000000-0000-0000-0000-000000000001",
        "login": "bob",
        "offer_slug": "standard",
        "state": "actif",
        "country_code": "FR",
        "currency": "EUR",
        "amount_minor": 1200,
    }
    base.update(extra)
    return Subscription.model_validate(base)


def test_la_table_couvre_tous_les_kinds_du_canal() -> None:
    """Exhaustivité : chaque kind du canal de vente a son événement applicatif."""
    assert set(TYPE_PAR_KIND) == set(get_args(EventKind))


def test_tous_les_types_emis_sont_au_registre() -> None:
    """Un type hors registre serait rejeté à l'émission — autant le savoir ici."""
    for t in TYPE_PAR_KIND.values():
        assert t in EVENT_TYPES, t
    assert TYPE_RETENTION_EXPIREE in EVENT_TYPES


@pytest.fixture
def emissions(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    vues: list[dict[str, Any]] = []

    async def _emit(event_type: str, **kwargs: Any) -> None:
        vues.append({"type": event_type, **kwargs})

    async def _get_offer(slug: str, _conn: Any) -> Offer | None:
        return Offer.model_validate(
            {
                "slug": slug,
                "hosting_type": "dedie",
                "variables": {"gabarit": "vm-8go"},
            }
        )

    async def _email_de(login: str, _conn: Any) -> str | None:
        return f"{login}@x.org"

    monkeypatch.setattr(bus, "emit_event", _emit)
    monkeypatch.setattr(db_offers, "get_offer", _get_offer)
    monkeypatch.setattr(db_user, "email_de", _email_de)
    return vues


async def test_le_payload_est_celui_decide_par_la_fiche(
    emissions: list[dict[str, Any]],
) -> None:
    await publier_evenement_abonnement(
        "activation", _abonnement(), provider_event_id="evt_1", conn=None
    )

    (vu,) = emissions
    assert vu["type"] == "subscription.activated"
    assert vu["dedup_key"] == "evt_1"
    assert vu["subject"]["user_id"] == "bob"
    assert vu["subject"]["user_email"] == "bob@x.org"
    assert vu["subject"]["offre_slug"] == "standard"
    assert vu["subject"]["subscription_id"] == _abonnement().id
    assert vu["subject"]["hosting_type"] == "dedie"
    assert vu["subject"]["variables"] == {"gabarit": "vm-8go"}


async def test_le_type_et_le_complement_se_substituent(
    emissions: list[dict[str, Any]],
) -> None:
    """Le chemin du scheduler : même payload de base, type et champs propres."""
    await publier_evenement_abonnement(
        "resiliation",
        _abonnement(state="resilie"),
        provider_event_id="retention:sub-1",
        conn=None,
        type_evenement=TYPE_RETENTION_EXPIREE,
        complement={"retention_jours": 30},
    )

    (vu,) = emissions
    assert vu["type"] == TYPE_RETENTION_EXPIREE
    assert vu["subject"]["state"] == "resilie"
    assert vu["subject"]["retention_jours"] == 30


async def test_une_offre_disparue_n_empeche_pas_l_emission(
    emissions: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """L'abonnement peut pointer une offre retirée : l'événement part quand
    même, avec ce qu'on sait — le supprimer cacherait la transition aux
    automates."""

    async def _aucune(slug: str, _conn: Any) -> None:
        return None

    monkeypatch.setattr(db_offers, "get_offer", _aucune)

    await publier_evenement_abonnement(
        "resiliation", _abonnement(), provider_event_id="evt_2", conn=None
    )

    (vu,) = emissions
    assert vu["subject"]["hosting_type"] == ""
    assert vu["subject"]["variables"] == {}


async def test_un_echec_d_emission_ne_remonte_jamais(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La transition est déjà actée côté fournisseur : un bus qui tousse se
    journalise, il ne fait pas rollback un paiement."""

    async def _explose(slug: str, _conn: Any) -> None:
        raise RuntimeError("db en panne")

    monkeypatch.setattr(db_offers, "get_offer", _explose)

    await publier_evenement_abonnement(
        "activation", _abonnement(), provider_event_id="evt_3", conn=None
    )
