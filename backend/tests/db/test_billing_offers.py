"""Persistance des taux de taxe et des offres.

Fixtures DB définies dans tests/conftest.py (postgres_url, db_engine, db_conn).

Ce que le faux store des tests de routes ne peut pas prouver et qui se joue ici :
que `NUMERIC` rend bien un `Decimal` exact, que remplacer une offre remplace
aussi ses prix, et qu'une offre souscrite est bien détectée comme référencée.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import insert

from portal.billing.models import Offer, OfferPrice, PaymentProvider, TaxRate
from portal.db.billing_catalog import upsert_provider
from portal.db.billing_offers import (
    add_tax_rate,
    close_tax_rate,
    delete_offer,
    delete_tax_rate,
    get_offer,
    get_tax_rate,
    list_offers,
    list_tax_rates,
    offer_reference,
    upsert_offer,
)
from portal.db.tables import countries, subscriptions, users

TVA20 = TaxRate(
    country_code="FR", rate=Decimal("0.2000"), label="TVA 20 %", valid_from=date(2024, 1, 1)
)
SOLO = Offer(
    slug="solo",
    labels={"fr": "Solo"},
    max_workspaces=3,
    prices=[OfferPrice(currency="EUR", amount_minor=1200)],
)


async def _seed_pays(conn, code: str = "FR") -> None:
    await conn.execute(insert(countries).values(code=code, label=code))


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


# ─── Taux de taxe ────────────────────────────────────────────────────────────


async def test_le_taux_revient_exact(db_conn) -> None:
    # NUMERIC et non float : sur de la facturation, l'erreur d'arrondi d'un
    # binaire flottant se découvre au rapprochement bancaire.
    await _seed_pays(db_conn)
    pose = await add_tax_rate(TVA20, db_conn)

    relu = await get_tax_rate(pose.id, db_conn)
    assert relu is not None
    assert relu.rate == Decimal("0.2000")


async def test_l_ajout_rend_l_identite(db_conn) -> None:
    await _seed_pays(db_conn)

    pose = await add_tax_rate(TVA20, db_conn)

    assert pose.id is not None


async def test_l_id_du_corps_est_ignore(db_conn) -> None:
    # C'est la base qui numérote : un client ne choisit pas son identifiant.
    await _seed_pays(db_conn)

    pose = await add_tax_rate(TVA20.model_copy(update={"id": 4242}), db_conn)

    assert pose.id != 4242


async def test_clore_pose_la_fin_sans_toucher_au_reste(db_conn) -> None:
    await _seed_pays(db_conn)
    pose = await add_tax_rate(TVA20, db_conn)

    assert await close_tax_rate(pose.id, date(2025, 1, 1), db_conn) is True

    relu = await get_tax_rate(pose.id, db_conn)
    assert relu is not None
    assert relu.valid_to == date(2025, 1, 1)
    assert relu.rate == Decimal("0.2000")


async def test_clore_un_taux_inconnu_ne_ment_pas(db_conn) -> None:
    assert await close_tax_rate(999, date(2025, 1, 1), db_conn) is False


async def test_l_historique_reste_complet(db_conn) -> None:
    # Un taux clos ne disparaît pas : c'est lui qui rend une facture ancienne
    # reproductible.
    await _seed_pays(db_conn)
    ancien = await add_tax_rate(TVA20, db_conn)
    await close_tax_rate(ancien.id, date(2025, 1, 1), db_conn)
    await add_tax_rate(
        TVA20.model_copy(update={"rate": Decimal("0.2100"), "valid_from": date(2025, 1, 1)}),
        db_conn,
    )

    historique = await list_tax_rates(db_conn, country_code="FR")
    assert [t.valid_from for t in historique] == [date(2024, 1, 1), date(2025, 1, 1)]


async def test_supprimer_un_taux(db_conn) -> None:
    await _seed_pays(db_conn)
    pose = await add_tax_rate(TVA20, db_conn)

    assert await delete_tax_rate(pose.id, db_conn) is True
    assert await list_tax_rates(db_conn) == []


async def test_supprimer_un_pays_emporte_ses_taux(db_conn) -> None:
    await _seed_pays(db_conn)
    await add_tax_rate(TVA20, db_conn)

    await db_conn.execute(countries.delete().where(countries.c.code == "FR"))

    assert await list_tax_rates(db_conn) == []


# ─── Offres ──────────────────────────────────────────────────────────────────


async def test_cree_puis_relit_une_offre_avec_ses_prix(db_conn) -> None:
    await upsert_offer(SOLO, db_conn)

    relu = await get_offer("solo", db_conn)
    assert relu is not None
    assert relu.prix("EUR").amount_minor == 1200
    assert relu.max_workspaces == 3


async def test_un_quota_illimite_reste_none(db_conn) -> None:
    # None = illimité. Le confondre avec 0 couperait tout net.
    await upsert_offer(SOLO.model_copy(update={"max_workspaces": None}), db_conn)

    relu = await get_offer("solo", db_conn)
    assert relu is not None
    assert relu.max_workspaces is None


async def test_remplacer_une_offre_remplace_ses_prix(db_conn) -> None:
    # Une devise retirée du corps doit disparaître, sans quoi elle resterait
    # vendable.
    await upsert_offer(
        SOLO.model_copy(
            update={
                "prices": [
                    OfferPrice(currency="EUR", amount_minor=1200),
                    OfferPrice(currency="USD", amount_minor=1400),
                ]
            }
        ),
        db_conn,
    )

    await upsert_offer(SOLO, db_conn)

    relu = await get_offer("solo", db_conn)
    assert relu is not None
    assert [p.currency for p in relu.prices] == ["EUR"]


async def test_une_offre_sans_prix_se_relit(db_conn) -> None:
    await upsert_offer(SOLO.model_copy(update={"prices": []}), db_conn)

    relu = await get_offer("solo", db_conn)
    assert relu is not None
    assert relu.prices == []


async def test_published_only_filtre(db_conn) -> None:
    await upsert_offer(SOLO.model_copy(update={"published": True}), db_conn)
    await upsert_offer(SOLO.model_copy(update={"slug": "team", "published": False}), db_conn)

    assert [o.slug for o in await list_offers(db_conn, published_only=True)] == ["solo"]
    assert len(await list_offers(db_conn)) == 2


async def test_le_provider_d_une_offre_est_conserve(db_conn) -> None:
    await upsert_provider(
        PaymentProvider(slug="stripe-fr", kind="stripe", label="Stripe FR"), db_conn
    )
    await upsert_offer(SOLO.model_copy(update={"provider_slug": "stripe-fr"}), db_conn)

    relu = await get_offer("solo", db_conn)
    assert relu is not None
    assert relu.provider_slug == "stripe-fr"


async def test_supprimer_une_offre_emporte_ses_prix(db_conn) -> None:
    await upsert_offer(SOLO, db_conn)

    assert await delete_offer("solo", db_conn) is True
    assert await get_offer("solo", db_conn) is None


async def test_une_offre_souscrite_est_referencee(db_conn) -> None:
    await _seed_user(db_conn)
    await upsert_offer(SOLO, db_conn)
    await db_conn.execute(
        insert(subscriptions).values(
            id=str(uuid.uuid4()),
            login="alice",
            offer_slug="solo",
            country_code="FR",
            currency="EUR",
            amount_minor=1200,
        )
    )

    assert await offer_reference("solo", db_conn) is True


async def test_une_offre_jamais_souscrite_ne_l_est_pas(db_conn) -> None:
    await upsert_offer(SOLO, db_conn)

    assert await offer_reference("solo", db_conn) is False
