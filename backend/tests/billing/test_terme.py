"""La clôture des forfaits à leur terme.

Ce que ces tests verrouillent : un forfait échu sans reconduction est RÉSILIÉ
(l'acteur de « s'arrêtera à son échéance »), une offre à reconduction tacite
n'est JAMAIS close par le terme, le journal porte l'idempotence (deux passes,
une seule clôture), et la course avec un webhook qui a clos entre-temps se
résout en silence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

import portal.billing.terme as terme
from portal.billing.models import Offer
from portal.billing.subscriptions import Subscription, SubscriptionEvent
from portal.billing.terme import cle_terme, clore_les_termes

ECHEANCE = datetime(2026, 9, 1, 9, 30, tzinfo=UTC)
MAINTENANT = datetime(2026, 9, 5, tzinfo=UTC)


def _abonnement(**extra: Any) -> Subscription:
    base: dict[str, Any] = {
        "id": "00000000-0000-0000-0000-000000000001",
        "login": "alice",
        "offer_slug": "welcome",
        "state": "essai",
        "country_code": "FR",
        "currency": "EUR",
        "amount_minor": 0,
        "ends_at": ECHEANCE,
    }
    base.update(extra)
    return Subscription.model_validate(base)


@pytest.fixture
def monde(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    import portal.db.engine as engine
    import portal.db.retention as db_retention
    import portal.db.subscription_events as db_events
    import portal.db.subscriptions as db_subs
    from portal.db import billing_offers as db_offers

    etat: dict[str, Any] = {
        "echus": [],
        "offres": {"welcome": Offer(slug="welcome", is_free=True, tacite_reconduction=False)},
        "journal": set(),
        "etats": [],
        "emis": [],
    }

    class _Txn:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *exc: Any) -> None:
            return None

    class _Moteur:
        def connect(self) -> _Txn:
            return _Txn()

        def begin(self) -> _Txn:
            return _Txn()

    async def _echus(_conn: Any, *, maintenant: Any) -> list[Subscription]:
        return list(etat["echus"])

    async def _get_offer(slug: str, _conn: Any) -> Offer | None:
        return etat["offres"].get(slug)

    async def _enregistrer(event: SubscriptionEvent, sid: str | None, _conn: Any) -> bool:
        cle = (event.provider_slug, event.provider_event_id)
        if cle in etat["journal"]:
            return False
        etat["journal"].add(cle)
        return True

    async def _enregistrer_etat(abonnement: Subscription, _conn: Any) -> None:
        etat["etats"].append(abonnement)

    async def _publier(kind: str, abonnement: Subscription, **kwargs: Any) -> None:
        etat["emis"].append({"kind": kind, "abonnement": abonnement, **kwargs})

    monkeypatch.setattr(engine, "_get_engine", lambda: _Moteur())
    monkeypatch.setattr(db_retention, "abonnements_a_terme", _echus)
    monkeypatch.setattr(db_offers, "get_offer", _get_offer)
    monkeypatch.setattr(db_events, "enregistrer", _enregistrer)
    monkeypatch.setattr(db_subs, "enregistrer_etat", _enregistrer_etat)
    monkeypatch.setattr(terme, "publier_evenement_abonnement", _publier)
    return etat


async def test_un_forfait_echu_est_resilie(monde: dict[str, Any]) -> None:
    monde["echus"] = [_abonnement()]

    clos = await clore_les_termes(MAINTENANT)

    assert clos == 1
    (maj,) = monde["etats"]
    assert maj.state == "resilie"
    (evt,) = monde["emis"]
    assert evt["kind"] == "resiliation"
    assert evt["provider_event_id"] == cle_terme(_abonnement())


async def test_la_reconduction_tacite_n_est_jamais_close_par_le_terme(
    monde: dict[str, Any],
) -> None:
    """Son forfait repart : c'est le canal de paiement qui gouverne son cycle."""
    monde["offres"]["welcome"] = Offer(slug="welcome", tacite_reconduction=True)
    monde["echus"] = [_abonnement()]

    assert await clore_les_termes(MAINTENANT) == 0
    assert monde["etats"] == []


async def test_deux_passes_ne_resilient_qu_une_fois(monde: dict[str, Any]) -> None:
    """Le journal tranche l'idempotence — même mécanique que les webhooks."""
    monde["echus"] = [_abonnement()]

    assert await clore_les_termes(MAINTENANT) == 1
    assert await clore_les_termes(MAINTENANT) == 0
    assert len(monde["etats"]) == 1


async def test_une_offre_disparue_clot_quand_meme(monde: dict[str, Any]) -> None:
    """L'abonnement pointe une offre retirée : dans le doute, le terme posé à
    la souscription fait foi — le service ne doit pas durer indéfiniment."""
    monde["offres"] = {}
    monde["echus"] = [_abonnement()]

    assert await clore_les_termes(MAINTENANT) == 1


async def test_la_course_avec_un_webhook_se_resout_en_silence(monde: dict[str, Any]) -> None:
    """Un webhook a clos l'abonnement entre la lecture et la passe : l'état
    voulu est déjà là, rien à réécrire."""
    monde["echus"] = [_abonnement(state="resilie")]

    assert await clore_les_termes(MAINTENANT) == 0
    assert monde["etats"] == []
