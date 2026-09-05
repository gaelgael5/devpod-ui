"""Persistance du catalogue de facturation : pays, devises, canaux de paiement.

Fixtures DB définies dans tests/conftest.py (postgres_url, db_engine, db_conn).
Ces tests exercent le VRAI schéma : ils sont là pour attraper ce qu'un faux
store ne peut pas attraper — les cascades, l'index partiel sur la devise par
défaut, et le comptage des références.
"""

from __future__ import annotations

import uuid

from sqlalchemy import insert

from portal.billing.models import Country, CountryProvider, Currency, PaymentProvider
from portal.db.billing_catalog import (
    delete_country,
    delete_provider,
    devises_actives,
    get_country,
    get_provider,
    list_countries,
    list_country_providers,
    list_currencies,
    list_providers,
    provider_reference,
    set_country_providers,
    set_currencies,
    upsert_country,
    upsert_provider,
)
from portal.db.tables import offers, subscriptions, users

FR = Country(code="FR", label="France")
BE = Country(code="BE", label="Belgique")
STRIPE = PaymentProvider(slug="stripe-fr", kind="stripe", label="Stripe France")


async def _seed_user(conn, login: str = "alice") -> None:
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


# ─── Pays ────────────────────────────────────────────────────────────────────


async def test_cree_puis_relit_un_pays(db_conn) -> None:
    await upsert_country(FR, db_conn)

    assert await get_country("FR", db_conn) == FR


async def test_upsert_remplace_sans_dupliquer(db_conn) -> None:
    await upsert_country(FR, db_conn)
    await upsert_country(FR.model_copy(update={"label": "France métropolitaine"}), db_conn)

    pays = await list_countries(db_conn)
    assert len(pays) == 1
    assert pays[0].label == "France métropolitaine"


async def test_liste_triee_par_libelle(db_conn) -> None:
    await upsert_country(FR, db_conn)
    await upsert_country(BE, db_conn)

    assert [p.code for p in await list_countries(db_conn)] == ["BE", "FR"]


async def test_supprimer_un_pays_inconnu_ne_ment_pas(db_conn) -> None:
    assert await delete_country("ZZ", db_conn) is False


async def test_supprimer_un_pays_ne_touche_pas_aux_devises(db_conn) -> None:
    # Les devises sont globales : ce que la plateforme sait encaisser ne depend
    # pas de l'existence d'un pays.
    await upsert_country(FR, db_conn)
    await set_currencies([Currency(code="EUR", is_default=True)], db_conn)

    await delete_country("FR", db_conn)

    assert [d.code for d in await list_currencies(db_conn)] == ["EUR"]


# ─── Devises acceptees par l'application ─────────────────────────────────────


async def test_remplace_le_jeu_de_devises(db_conn) -> None:
    await set_currencies(
        [Currency(code="EUR", is_default=True), Currency(code="USD")],
        db_conn,
    )

    await set_currencies([Currency(code="CHF", is_default=True)], db_conn)

    assert [d.code for d in await list_currencies(db_conn)] == ["CHF"]


async def test_le_defaut_peut_changer_de_devise(db_conn) -> None:
    # L'index partiel unique refuserait deux défauts : effacer puis réinsérer
    # est justement ce qui évite l'état transitoire interdit.
    await set_currencies([Currency(code="EUR", is_default=True)], db_conn)

    await set_currencies(
        [Currency(code="EUR"), Currency(code="USD", is_default=True)],
        db_conn,
    )

    assert [d.code for d in await list_currencies(db_conn) if d.is_default] == ["USD"]


async def test_devises_actives_ignore_les_devises_desactivees(db_conn) -> None:
    # Une offre n'a pas a porter un prix dans une devise qu'on n'encaisse plus.
    await set_currencies(
        [Currency(code="EUR", is_default=True), Currency(code="CHF", enabled=False)],
        db_conn,
    )

    assert await devises_actives(db_conn) == ["EUR"]


async def test_devises_actives_triees(db_conn) -> None:
    await set_currencies(
        [Currency(code="USD"), Currency(code="EUR", is_default=True)],
        db_conn,
    )

    assert await devises_actives(db_conn) == ["EUR", "USD"]


# ─── Canaux de paiement ──────────────────────────────────────────────────────


async def test_cree_puis_relit_un_provider(db_conn) -> None:
    await upsert_provider(STRIPE, db_conn)

    assert await get_provider("stripe-fr", db_conn) == STRIPE


async def test_la_config_survit_a_l_aller_retour(db_conn) -> None:
    provider = STRIPE.model_copy(update={"config": {"account_id": "acct_42"}})
    await upsert_provider(provider, db_conn)

    relu = await get_provider("stripe-fr", db_conn)
    assert relu is not None
    assert relu.config == {"account_id": "acct_42"}


async def test_aucune_cle_api_n_est_stockee(db_conn) -> None:
    # `secret_slug` est une RÉFÉRENCE vers la table des secrets, jamais la clé.
    await upsert_provider(
        STRIPE.model_copy(update={"secret_slug": "billing/stripe_api_key"}), db_conn
    )

    relu = await get_provider("stripe-fr", db_conn)
    assert relu is not None
    assert relu.secret_slug == "billing/stripe_api_key"


async def test_upsert_provider_remplace_sans_dupliquer(db_conn) -> None:
    await upsert_provider(STRIPE, db_conn)
    await upsert_provider(STRIPE.model_copy(update={"enabled": False}), db_conn)

    tous = await list_providers(db_conn)
    assert len(tous) == 1
    assert tous[0].enabled is False


async def test_un_provider_libre_se_supprime(db_conn) -> None:
    await upsert_provider(STRIPE, db_conn)

    assert await delete_provider("stripe-fr", db_conn) is True
    assert await list_providers(db_conn) == []


async def test_un_provider_porte_par_une_offre_est_reference(db_conn) -> None:
    await upsert_provider(STRIPE, db_conn)
    await db_conn.execute(insert(offers).values(slug="solo", provider_slug="stripe-fr"))

    assert await provider_reference("stripe-fr", db_conn) is True


async def test_un_provider_porte_par_un_abonnement_est_reference(db_conn) -> None:
    await _seed_user(db_conn)
    await upsert_provider(STRIPE, db_conn)
    await db_conn.execute(insert(offers).values(slug="solo"))
    await db_conn.execute(
        insert(subscriptions).values(
            id=str(uuid.uuid4()),
            login="alice",
            offer_slug="solo",
            provider_slug="stripe-fr",
            country_code="FR",
            currency="EUR",
            amount_minor=1200,
        )
    )

    assert await provider_reference("stripe-fr", db_conn) is True


async def test_un_provider_sans_reference_ne_l_est_pas(db_conn) -> None:
    await upsert_provider(STRIPE, db_conn)

    assert await provider_reference("stripe-fr", db_conn) is False


# ─── Rattachement pays ↔ providers ───────────────────────────────────────────


async def test_rattachements_rendus_par_priorite_croissante(db_conn) -> None:
    await upsert_country(FR, db_conn)
    await upsert_provider(STRIPE, db_conn)
    await upsert_provider(
        PaymentProvider(slug="stripe-bis", kind="stripe", label="Stripe bis"), db_conn
    )

    await set_country_providers(
        "FR",
        [
            CountryProvider(country_code="FR", provider_slug="stripe-bis", priority=5),
            CountryProvider(country_code="FR", provider_slug="stripe-fr", priority=1),
        ],
        db_conn,
    )

    assert [x.provider_slug for x in await list_country_providers(db_conn, country_code="FR")] == [
        "stripe-fr",
        "stripe-bis",
    ]


async def test_supprimer_un_provider_emporte_ses_rattachements(db_conn) -> None:
    await upsert_country(FR, db_conn)
    await upsert_provider(STRIPE, db_conn)
    await set_country_providers(
        "FR", [CountryProvider(country_code="FR", provider_slug="stripe-fr")], db_conn
    )

    await delete_provider("stripe-fr", db_conn)

    assert await list_country_providers(db_conn) == []


async def test_rattachements_remplaces_et_non_cumules(db_conn) -> None:
    await upsert_country(FR, db_conn)
    await upsert_provider(STRIPE, db_conn)
    await set_country_providers(
        "FR", [CountryProvider(country_code="FR", provider_slug="stripe-fr")], db_conn
    )

    await set_country_providers("FR", [], db_conn)

    # Le corps reçu décrit l'état voulu, pas un delta : une liste vide vide.
    assert await list_country_providers(db_conn, country_code="FR") == []
    assert await get_provider("stripe-fr", db_conn) is not None
