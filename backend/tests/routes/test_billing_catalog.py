"""API du catalogue de facturation : pays, devises, canaux de paiement.

Ce sont les données qui décident de ce qu'on peut vendre, où, et par quel
canal. Réservé aux administrateurs.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.auth.rbac import UserInfo, require_admin
from portal.billing.models import Country, CountryProvider, Currency, PaymentProvider
from portal.db.engine import get_conn
from portal.routes import billing_catalog


class _Store:
    """Base simulée : c'est le comportement des routes qu'on teste."""

    def __init__(self) -> None:
        self.pays: dict[str, Country] = {}
        #: Jeu GLOBAL de devises acceptees par l'application.
        self.devises: list[Currency] = []
        self.providers: dict[str, PaymentProvider] = {}
        self.liens: dict[str, list[CountryProvider]] = {}
        #: Slugs de providers qu'une offre ou un abonnement référence.
        self.providers_references: set[str] = set()


@pytest.fixture
def store() -> _Store:
    s = _Store()
    s.providers["stripe-fr"] = PaymentProvider(slug="stripe-fr", kind="stripe", label="Stripe FR")
    return s


@pytest.fixture
def client(store: _Store, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(billing_catalog.router, prefix="/admin")
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="admin", roles=["admin"])
    app.dependency_overrides[get_conn] = lambda: None

    async def _list_countries(_conn: Any) -> list[Country]:
        return sorted(store.pays.values(), key=lambda c: c.label)

    async def _get_country(code: str, _conn: Any) -> Country | None:
        return store.pays.get(code)

    async def _upsert_country(pays: Country, _conn: Any) -> None:
        store.pays[pays.code] = pays

    async def _delete_country(code: str, _conn: Any) -> bool:
        store.liens.pop(code, None)
        return store.pays.pop(code, None) is not None

    async def _list_currencies(_conn: Any) -> list[Currency]:
        return list(store.devises)

    async def _set_currencies(devises: list[Currency], _conn: Any) -> None:
        store.devises = list(devises)

    async def _list_providers(_conn: Any) -> list[PaymentProvider]:
        return sorted(store.providers.values(), key=lambda p: p.label)

    async def _get_provider(slug: str, _conn: Any) -> PaymentProvider | None:
        return store.providers.get(slug)

    async def _upsert_provider(provider: PaymentProvider, _conn: Any) -> None:
        store.providers[provider.slug] = provider

    async def _delete_provider(slug: str, _conn: Any) -> bool:
        return store.providers.pop(slug, None) is not None

    async def _provider_reference(slug: str, _conn: Any) -> bool:
        return slug in store.providers_references

    async def _list_liens(_conn: Any, *, country_code: str | None = None) -> list[CountryProvider]:
        if country_code is not None:
            return list(store.liens.get(country_code, []))
        return [x for lot in store.liens.values() for x in lot]

    async def _set_liens(code: str, liens: list[CountryProvider], _conn: Any) -> None:
        store.liens[code] = list(liens)

    for nom, impl in {
        "list_countries": _list_countries,
        "get_country": _get_country,
        "upsert_country": _upsert_country,
        "delete_country": _delete_country,
        "list_currencies": _list_currencies,
        "set_currencies": _set_currencies,
        "list_providers": _list_providers,
        "get_provider": _get_provider,
        "upsert_provider": _upsert_provider,
        "delete_provider": _delete_provider,
        "provider_reference": _provider_reference,
        "list_country_providers": _list_liens,
        "set_country_providers": _set_liens,
    }.items():
        monkeypatch.setattr(billing_catalog, nom, impl)
    return TestClient(app)


# ─── Pays ────────────────────────────────────────────────────────────────────


def test_cree_un_pays(client: TestClient, store: _Store) -> None:
    res = client.put("/admin/billing/countries/FR", json={"code": "FR", "label": "France"})

    assert res.status_code == 200
    assert store.pays["FR"].label == "France"


def test_le_code_de_l_url_fait_foi(client: TestClient, store: _Store) -> None:
    # Sans ce garde-fou, un PUT sur /FR écraserait le pays BE.
    res = client.put("/admin/billing/countries/FR", json={"code": "BE", "label": "Belgique"})

    assert res.status_code == 422
    assert store.pays == {}


def test_refuse_un_code_pays_hors_iso(client: TestClient) -> None:
    res = client.put("/admin/billing/countries/fra", json={"code": "fra", "label": "France"})

    assert res.status_code == 422


def test_liste_les_pays_tries_par_libelle(client: TestClient) -> None:
    client.put("/admin/billing/countries/FR", json={"code": "FR", "label": "France"})
    client.put("/admin/billing/countries/BE", json={"code": "BE", "label": "Belgique"})

    res = client.get("/admin/billing/countries")

    assert [p["code"] for p in res.json()] == ["BE", "FR"]


def test_supprimer_un_pays_inconnu_est_un_404(client: TestClient) -> None:
    assert client.delete("/admin/billing/countries/ZZ").status_code == 404


# ─── Devises acceptees par l'application ─────────────────────────────────────


def test_remplace_le_jeu_de_devises(client: TestClient, store: _Store) -> None:
    res = client.put(
        "/admin/billing/currencies",
        json=[{"code": "EUR", "enabled": True, "is_default": True}],
    )

    assert res.status_code == 200
    assert [d.code for d in store.devises] == ["EUR"]


def test_refuse_deux_devises_par_defaut(client: TestClient) -> None:
    # Deux défauts rendraient indéterminé le choix au moment de présenter un prix.
    res = client.put(
        "/admin/billing/currencies",
        json=[
            {"code": "EUR", "is_default": True},
            {"code": "USD", "is_default": True},
        ],
    )

    assert res.status_code == 422
    assert "défaut" in res.json()["detail"]


def test_refuse_un_jeu_de_devises_sans_defaut(client: TestClient) -> None:
    res = client.put("/admin/billing/currencies", json=[{"code": "EUR", "is_default": False}])

    assert res.status_code == 422


def test_refuse_une_devise_repetee(client: TestClient) -> None:
    res = client.put(
        "/admin/billing/currencies",
        json=[{"code": "EUR", "is_default": True}, {"code": "EUR"}],
    )

    assert res.status_code == 422
    assert "répétée" in res.json()["detail"]


def test_refuse_un_defaut_desactive(client: TestClient) -> None:
    # Une devise par défaut qu'on n'encaisse pas ne vaut pas mieux qu'aucune.
    res = client.put(
        "/admin/billing/currencies",
        json=[{"code": "EUR", "enabled": False, "is_default": True}],
    )

    assert res.status_code == 422


def test_jeu_vide_accepte(client: TestClient, store: _Store) -> None:
    # Aucune devise = rien n'est vendable, mais c'est un etat de configuration
    # legitime : le garde-fou a la publication le dira, pas cette route.
    res = client.put("/admin/billing/currencies", json=[])

    assert res.status_code == 200
    assert store.devises == []



# ─── Canaux de paiement ──────────────────────────────────────────────────────


def test_cree_un_provider(client: TestClient, store: _Store) -> None:
    res = client.put(
        "/admin/billing/providers/stripe-test",
        json={
            "slug": "stripe-test",
            "kind": "stripe",
            "label": "Stripe test",
            "config": {"account_id": "acct_123"},
        },
    )

    assert res.status_code == 200
    assert store.providers["stripe-test"].config["account_id"] == "acct_123"


def test_refuse_une_config_etrangere_au_kind(client: TestClient) -> None:
    # Une clé inconnue est refusée à la saisie, pas découverte au premier paiement.
    res = client.put(
        "/admin/billing/providers/stripe-test",
        json={
            "slug": "stripe-test",
            "kind": "stripe",
            "label": "Stripe test",
            "config": {"compte": "acct_123"},
        },
    )

    assert res.status_code == 422


def test_aucun_secret_dans_la_reponse_d_un_provider(client: TestClient) -> None:
    res = client.put(
        "/admin/billing/providers/stripe-test",
        json={
            "slug": "stripe-test",
            "kind": "stripe",
            "label": "Stripe test",
            "secret_slug": "billing/stripe_api_key",
        },
    )

    # `secret_slug` est une RÉFÉRENCE : elle a le droit de circuler, la clé non.
    assert res.json()["secret_slug"] == "billing/stripe_api_key"
    assert "sk_" not in res.text


def test_refuse_de_supprimer_un_provider_reference(client: TestClient, store: _Store) -> None:
    store.providers_references.add("stripe-fr")

    res = client.delete("/admin/billing/providers/stripe-fr")

    assert res.status_code == 409
    assert "stripe-fr" in store.providers


def test_supprime_un_provider_libre(client: TestClient, store: _Store) -> None:
    assert client.delete("/admin/billing/providers/stripe-fr").status_code == 204
    assert store.providers == {}


# ─── Rattachement pays ↔ providers ───────────────────────────────────────────


def test_rattache_des_providers_ordonnes(client: TestClient, store: _Store) -> None:
    client.put("/admin/billing/countries/FR", json={"code": "FR", "label": "France"})

    res = client.put(
        "/admin/billing/countries/FR/providers",
        json=[{"country_code": "FR", "provider_slug": "stripe-fr", "priority": 10}],
    )

    assert res.status_code == 200
    assert store.liens["FR"][0].priority == 10


def test_refuse_un_rattachement_vers_un_provider_inconnu(client: TestClient) -> None:
    client.put("/admin/billing/countries/FR", json={"code": "FR", "label": "France"})

    res = client.put(
        "/admin/billing/countries/FR/providers",
        json=[{"country_code": "FR", "provider_slug": "paypal", "priority": 0}],
    )

    assert res.status_code == 422
    assert "paypal" in res.json()["detail"]


def test_refuse_deux_fois_le_meme_provider(client: TestClient) -> None:
    client.put("/admin/billing/countries/FR", json={"code": "FR", "label": "France"})

    res = client.put(
        "/admin/billing/countries/FR/providers",
        json=[
            {"country_code": "FR", "provider_slug": "stripe-fr", "priority": 0},
            {"country_code": "FR", "provider_slug": "stripe-fr", "priority": 1},
        ],
    )

    assert res.status_code == 422
