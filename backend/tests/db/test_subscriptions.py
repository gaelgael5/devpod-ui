"""Persistance des abonnements, contre le vrai schéma.

Ce que le faux store des tests de routes ne peut pas prouver : que l'instantané
du prix revient exact, que l'échéance survit au passage en base, et surtout que
`offres_deja_souscrites` compte bien les abonnements RÉSILIÉS — sans quoi il
suffirait de résilier pour reprendre une offre de bienvenue.

Fixtures DB dans tests/conftest.py (postgres_url, db_engine, db_conn).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import insert

from portal.billing.subscriptions import Subscription, fin_de_forfait
from portal.db.subscriptions import creer, get, list_de, offres_deja_souscrites
from portal.db.tables import countries, offers, users


async def _seed_socle(conn) -> None:
    await conn.execute(insert(countries).values(code="FR", label="France"))
    await conn.execute(insert(offers).values(slug="standard", label="Standard"))
    await conn.execute(insert(offers).values(slug="welcome", label="Welcome"))
    for login in ("alice", "bob"):
        await conn.execute(
            insert(users).values(
                login=login,
                version="1",
                secret_ns=str(uuid.uuid4()),
                default_ide="openvscode",
                default_idle_timeout="2h",
                harpocrate_api_key="",
            )
        )


def _abonnement(**extra) -> Subscription:
    base = {
        "id": str(uuid.uuid4()),
        "login": "alice",
        "offer_slug": "standard",
        "state": "essai",
        "country_code": "FR",
        "currency": "EUR",
        "amount_minor": 1200,
        "ends_at": fin_de_forfait(datetime.now(UTC), 30),
    }
    base.update(extra)
    return Subscription.model_validate(base)


async def test_un_abonnement_revient_exact(db_conn) -> None:
    await _seed_socle(db_conn)
    pose = _abonnement()

    await creer(pose, db_conn)
    relu = await get(pose.id, db_conn)

    assert relu is not None
    assert relu.login == "alice"
    assert relu.offer_slug == "standard"
    assert relu.state == "essai"
    assert relu.country_code == "FR"
    # L'instantané du prix : le catalogue évoluera, cet abonné garde le sien.
    assert relu.currency == "EUR"
    assert relu.amount_minor == 1200
    assert relu.ends_at == pose.ends_at


async def test_un_abonnement_inconnu_rend_none(db_conn) -> None:
    await _seed_socle(db_conn)

    assert await get(str(uuid.uuid4()), db_conn) is None


async def test_lister_ne_rend_que_ses_abonnements(db_conn) -> None:
    await _seed_socle(db_conn)
    await creer(_abonnement(login="alice"), db_conn)
    await creer(_abonnement(login="bob"), db_conn)

    assert [s.login for s in await list_de("alice", db_conn)] == ["alice"]


async def test_deux_souscriptions_a_la_meme_offre_coexistent(db_conn) -> None:
    """Prendre deux fois le même forfait est légitime : rien ne l'empêche en base."""
    await _seed_socle(db_conn)
    await creer(_abonnement(), db_conn)
    await creer(_abonnement(), db_conn)

    assert len(await list_de("alice", db_conn)) == 2


# ─── La règle `une_par_compte` s'appuie là-dessus ────────────────────────────


async def test_les_offres_deja_souscrites_sont_listees(db_conn) -> None:
    await _seed_socle(db_conn)
    await creer(_abonnement(offer_slug="welcome"), db_conn)

    assert await offres_deja_souscrites("alice", db_conn) == {"welcome"}


async def test_un_abonnement_resilie_compte_toujours(db_conn) -> None:
    """LE test de cette règle.

    Sans lui, il suffirait de résilier pour reprendre une offre de bienvenue —
    ce qui viderait `une_par_compte` de son sens.
    """
    await _seed_socle(db_conn)
    await creer(_abonnement(offer_slug="welcome", state="resilie"), db_conn)

    assert await offres_deja_souscrites("alice", db_conn) == {"welcome"}


async def test_les_offres_d_un_autre_compte_ne_comptent_pas(db_conn) -> None:
    await _seed_socle(db_conn)
    await creer(_abonnement(login="bob", offer_slug="welcome"), db_conn)

    assert await offres_deja_souscrites("alice", db_conn) == set()


async def test_l_offre_ouverte_est_celle_du_dernier_abonnement_vivant(db_conn) -> None:
    """« Le forfait choisi » des événements user.* : l'abonnement OUVERT du
    compte — un résilié d'hier ne compte pas, un compte sans abonnement rend None."""
    from portal.db.subscriptions import offre_ouverte_de

    await _seed_socle(db_conn)
    await creer(_abonnement(offer_slug="welcome", state="resilie"), db_conn)

    assert await offre_ouverte_de("alice", db_conn) is None

    await creer(_abonnement(offer_slug="standard", state="actif"), db_conn)

    assert await offre_ouverte_de("alice", db_conn) == "standard"
    assert await offre_ouverte_de("bob", db_conn) is None
