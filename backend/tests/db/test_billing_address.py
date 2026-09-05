"""L'adresse de facturation chiffrée, contre le vrai schéma.

Le test qui compte est celui de la fiche : l'adresse se relit **sans que
l'utilisateur ait déverrouillé quoi que ce soit** — la clef vient du KEK seul,
jamais d'un PIN. Et l'adresse FIGÉE sur un abonnement ne bouge pas quand le
profil change : réécrire l'adresse d'une facture émise serait une falsification.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import insert, select

from portal.billing.adresse import AdresseFacturation
from portal.billing.subscriptions import Subscription
from portal.db.billing_address import (
    adresse_figee,
    figer_adresse,
    lire_adresse,
    poser_adresse,
)
from portal.db.subscriptions import creer
from portal.db.tables import billing_addresses, countries, offers, users


@pytest.fixture(autouse=True)
def _kek():
    # La SEULE matière de la clef : le KEK serveur. Aucun PIN nulle part —
    # c'est précisément ce que la fiche demande de prouver.
    with patch("portal.secrets.chiffrement.get_settings") as mock:
        mock.return_value.portal_vault_kek = "ab" * 32
        yield


def _adresse(**extra) -> AdresseFacturation:
    base = {
        "line1": "12 rue des Lilas",
        "city": "Lyon",
        "postal_code": "69003",
        "country": "FR",
    }
    base.update(extra)
    return AdresseFacturation.model_validate(base)


async def _seed_compte(conn, login: str = "alice") -> None:
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


async def test_l_adresse_se_relit_sans_aucun_deverrouillage(db_conn) -> None:
    await _seed_compte(db_conn)

    await poser_adresse("alice", _adresse(), db_conn)
    relue = await lire_adresse("alice", db_conn)

    assert relue == _adresse()


async def test_rien_n_est_stocke_en_clair(db_conn) -> None:
    await _seed_compte(db_conn)
    await poser_adresse("alice", _adresse(), db_conn)

    blob = (
        await db_conn.execute(
            select(billing_addresses.c.adresse_enc).where(billing_addresses.c.login == "alice")
        )
    ).scalar_one()

    for morceau in (b"Lilas", b"Lyon", b"69003"):
        assert morceau not in blob


async def test_reposer_remplace_l_adresse_courante(db_conn) -> None:
    await _seed_compte(db_conn)
    await poser_adresse("alice", _adresse(), db_conn)

    await poser_adresse("alice", _adresse(city="Paris", postal_code="75011"), db_conn)

    relue = await lire_adresse("alice", db_conn)
    assert relue is not None and relue.city == "Paris"


async def test_un_compte_sans_adresse_rend_none(db_conn) -> None:
    await _seed_compte(db_conn)

    assert await lire_adresse("alice", db_conn) is None


async def test_l_adresse_figee_survit_au_changement_de_profil(db_conn) -> None:
    """Le point de la fiche : modifier son profil ne change AUCUNE souscription
    passée — l'adresse d'une facture émise ne se réécrit pas."""
    await _seed_compte(db_conn)
    await db_conn.execute(insert(countries).values(code="FR", label="France"))
    await db_conn.execute(insert(offers).values(slug="standard", label="Standard"))
    abonnement = Subscription.model_validate(
        {
            "id": str(uuid.uuid4()),
            "login": "alice",
            "offer_slug": "standard",
            "state": "essai",
            "country_code": "FR",
            "currency": "EUR",
            "amount_minor": 0,
        }
    )
    await creer(abonnement, db_conn)
    await figer_adresse(abonnement.id, _adresse(), db_conn)

    await poser_adresse("alice", _adresse(city="Paris", postal_code="75011"), db_conn)

    figee = await adresse_figee(abonnement.id, db_conn)
    assert figee is not None and figee.city == "Lyon"


async def test_un_abonnement_sans_adresse_figee_rend_none(db_conn) -> None:
    await _seed_compte(db_conn)
    await db_conn.execute(insert(countries).values(code="FR", label="France"))
    await db_conn.execute(insert(offers).values(slug="standard", label="Standard"))
    abonnement = Subscription.model_validate(
        {
            "id": str(uuid.uuid4()),
            "login": "alice",
            "offer_slug": "standard",
            "state": "essai",
            "country_code": "FR",
            "currency": "EUR",
            "amount_minor": 0,
        }
    )
    await creer(abonnement, db_conn)

    assert await adresse_figee(abonnement.id, db_conn) is None
