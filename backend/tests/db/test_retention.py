"""Repérage des abonnements en retard de rétention, contre le vrai schéma.

Ce que ces tests verrouillent — c'est la seule mécanique du lot qui mène à
détruire des données :

- chaque état a SON délai (échec de paiement ≠ résiliation) ;
- un épisode déjà notifié ne revient JAMAIS dans la liste ;
- la réservation est tranchée par la contrainte d'unicité, pas par une lecture ;
- un nouvel épisode (état retombé après rétablissement) est notifié à son tour.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert

from portal.billing.config import PolitiqueRetention
from portal.billing.subscriptions import Subscription
from portal.db.retention import abonnements_en_retard, marquer_notifie
from portal.db.subscriptions import creer, get
from portal.db.tables import countries, offers, subscriptions, users

POLITIQUE = PolitiqueRetention(echec_paiement_jours=14, resiliation_jours=30)
MAINTENANT = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


async def _seed_socle(conn) -> None:
    await conn.execute(insert(countries).values(code="FR", label="France"))
    await conn.execute(insert(offers).values(slug="standard", label="Standard"))
    await conn.execute(
        insert(users).values(
            login="alice",
            version="1",
            secret_ns=str(uuid.uuid4()),
            default_ide="openvscode",
            default_idle_timeout="2h",
            harpocrate_api_key="",
        )
    )


async def _abonnement(conn, *, state: str, depuis_jours: int) -> Subscription:
    pose = Subscription.model_validate(
        {
            "id": str(uuid.uuid4()),
            "login": "alice",
            "offer_slug": "standard",
            "state": state,
            "country_code": "FR",
            "currency": "EUR",
            "amount_minor": 0,
        }
    )
    await creer(pose, conn)
    quand = MAINTENANT - timedelta(days=depuis_jours)
    await conn.execute(
        subscriptions.update().where(subscriptions.c.id == pose.id).values(state_changed_at=quand)
    )
    relu = await get(pose.id, conn)
    assert relu is not None
    return relu


async def test_chaque_etat_a_son_delai(db_conn) -> None:
    await _seed_socle(db_conn)
    echec_recent = await _abonnement(db_conn, state="echec_paiement", depuis_jours=10)
    echec_du = await _abonnement(db_conn, state="echec_paiement", depuis_jours=15)
    resilie_recent = await _abonnement(db_conn, state="resilie", depuis_jours=15)
    resilie_du = await _abonnement(db_conn, state="resilie", depuis_jours=31)

    en_retard = await abonnements_en_retard(db_conn, maintenant=MAINTENANT, politique=POLITIQUE)

    ids = {s.id for s in en_retard}
    assert echec_du.id in ids
    assert resilie_du.id in ids
    assert echec_recent.id not in ids
    assert resilie_recent.id not in ids


async def test_les_etats_vivants_ne_sont_jamais_en_retard(db_conn) -> None:
    """Un essai ou un actif ANCIEN n'est pas un candidat à la destruction —
    c'est le terme du forfait qui les gouverne, pas la rétention."""
    await _seed_socle(db_conn)
    await _abonnement(db_conn, state="essai", depuis_jours=100)
    await _abonnement(db_conn, state="actif", depuis_jours=100)

    assert await abonnements_en_retard(db_conn, maintenant=MAINTENANT, politique=POLITIQUE) == []


async def test_un_episode_notifie_ne_revient_pas(db_conn) -> None:
    await _seed_socle(db_conn)
    du = await _abonnement(db_conn, state="resilie", depuis_jours=31)
    assert du.state_changed_at is not None

    assert (
        await marquer_notifie(
            db_conn,
            subscription_id=du.id,
            state=du.state,
            state_changed_at=du.state_changed_at,
        )
        is True
    )

    assert await abonnements_en_retard(db_conn, maintenant=MAINTENANT, politique=POLITIQUE) == []


async def test_la_reservation_est_idempotente(db_conn) -> None:
    """Deux passes concurrentes du balayeur : la seconde rend False et n'émet
    donc rien — c'est la contrainte d'unicité qui tranche, pas une lecture."""
    await _seed_socle(db_conn)
    du = await _abonnement(db_conn, state="resilie", depuis_jours=31)
    assert du.state_changed_at is not None
    cle = {
        "subscription_id": du.id,
        "state": du.state,
        "state_changed_at": du.state_changed_at,
    }

    assert await marquer_notifie(db_conn, **cle) is True
    assert await marquer_notifie(db_conn, **cle) is False


async def test_un_nouvel_episode_est_notifie_a_son_tour(db_conn) -> None:
    """Un abonnement rétabli puis retombé en échec a un nouveau
    `state_changed_at` : l'ancienne notification ne le couvre pas."""
    await _seed_socle(db_conn)
    du = await _abonnement(db_conn, state="echec_paiement", depuis_jours=40)
    assert du.state_changed_at is not None
    await marquer_notifie(
        db_conn,
        subscription_id=du.id,
        state=du.state,
        state_changed_at=du.state_changed_at - timedelta(days=90),
    )

    en_retard = await abonnements_en_retard(db_conn, maintenant=MAINTENANT, politique=POLITIQUE)

    assert [s.id for s in en_retard] == [du.id]
