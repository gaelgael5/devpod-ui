"""Le balayeur de rétention : la logique, sans base.

Ce que ces tests verrouillent : le balayeur RÉSERVE avant d'émettre (l'épisode
déjà pris n'émet pas), l'événement émis est `subscription.retention_expired`
avec le délai appliqué, et la politique refuse un état qu'elle ne connaît pas —
plutôt qu'un délai par défaut silencieux sur le chemin qui détruit des données.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

import portal.billing.retention as retention
from portal.billing.config import PolitiqueRetention
from portal.billing.retention import balayer, cle_episode
from portal.billing.subscriptions import Subscription


def _abonnement(**extra: Any) -> Subscription:
    base: dict[str, Any] = {
        "id": "00000000-0000-0000-0000-000000000001",
        "login": "alice",
        "offer_slug": "standard",
        "state": "resilie",
        "country_code": "FR",
        "currency": "EUR",
        "amount_minor": 0,
        "state_changed_at": datetime(2026, 8, 1, 9, 30, tzinfo=UTC),
    }
    base.update(extra)
    return Subscription.model_validate(base)


def test_la_politique_refuse_un_etat_inconnu() -> None:
    with pytest.raises(ValueError):
        PolitiqueRetention().delai_jours("essai")


def test_la_cle_d_episode_est_stable_et_discriminante() -> None:
    a = _abonnement()
    assert cle_episode(a) == cle_episode(a)
    # Un nouvel épisode (autre instant de bascule) a une AUTRE clé : le
    # dédupliquer avec l'ancien masquerait une seconde destruction légitime.
    b = _abonnement(state_changed_at=datetime(2026, 9, 1, tzinfo=UTC))
    assert cle_episode(a) != cle_episode(b)


@pytest.fixture
def monde(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    import portal.config.store as store
    import portal.db.engine as engine
    import portal.db.retention as db_retention

    etat: dict[str, Any] = {
        "en_retard": [],
        "reserves": set(),
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

    class _Config:
        billing = type(
            "B",
            (),
            {"retention": PolitiqueRetention(echec_paiement_jours=14, resiliation_jours=30)},
        )()

    async def _en_retard(_conn: Any, *, maintenant: Any, politique: Any) -> list[Subscription]:
        return list(etat["en_retard"])

    async def _marquer(
        _conn: Any, *, subscription_id: str, state: str, state_changed_at: Any
    ) -> bool:
        cle = (subscription_id, state, state_changed_at)
        if cle in etat["reserves"]:
            return False
        etat["reserves"].add(cle)
        return True

    async def _publier(kind: str, abonnement: Subscription, **kwargs: Any) -> None:
        etat["emis"].append({"kind": kind, "abonnement": abonnement, **kwargs})

    monkeypatch.setattr(store, "load_global", lambda: _Config())
    monkeypatch.setattr(engine, "_get_engine", lambda: _Moteur())
    monkeypatch.setattr(db_retention, "abonnements_en_retard", _en_retard)
    monkeypatch.setattr(db_retention, "marquer_notifie", _marquer)
    monkeypatch.setattr(retention, "publier_evenement_abonnement", _publier)
    return etat


async def test_un_retard_emet_l_evenement_avec_son_delai(monde: dict[str, Any]) -> None:
    monde["en_retard"] = [_abonnement()]

    emis = await balayer(datetime(2026, 9, 5, tzinfo=UTC))

    assert emis == 1
    (evt,) = monde["emis"]
    assert evt["type_evenement"] == "subscription.retention_expired"
    assert evt["kind"] == "resiliation"
    assert evt["complement"]["retention_jours"] == 30
    assert evt["provider_event_id"] == cle_episode(_abonnement())


async def test_un_episode_deja_reserve_n_emet_pas(monde: dict[str, Any]) -> None:
    """Le défaut que la fiche interdit : deux passes, deux événements, deux
    destructions. La réservation tranche AVANT l'émission."""
    monde["en_retard"] = [_abonnement()]

    assert await balayer(datetime(2026, 9, 5, tzinfo=UTC)) == 1
    monde["emis"].clear()
    assert await balayer(datetime(2026, 9, 5, tzinfo=UTC)) == 0
    assert monde["emis"] == []


async def test_l_echec_de_paiement_porte_son_propre_delai(monde: dict[str, Any]) -> None:
    monde["en_retard"] = [_abonnement(state="echec_paiement")]

    await balayer(datetime(2026, 9, 5, tzinfo=UTC))

    (evt,) = monde["emis"]
    assert evt["kind"] == "echec_paiement"
    assert evt["complement"]["retention_jours"] == 14
