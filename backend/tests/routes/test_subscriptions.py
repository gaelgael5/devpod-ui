"""Souscription d'un forfait, vue de l'API.

Ce que cette route fait, et ce qu'elle NE fait pas : elle crée l'abonnement, et
rien d'autre. Ni paiement, ni provisionnement, ni message — chacun a son étape.

Une offre gratuite est donc souscriptible de bout en bout aujourd'hui ; c'est le
seul parcours exerçable tant qu'aucun compte de paiement n'existe, et c'est pour
cette raison qu'il est couvert en premier.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.auth.rbac import UserInfo, require_user
from portal.billing.models import Country, CountryProvider, Offer, OfferPrice
from portal.billing.subscriptions import Subscription
from portal.db.engine import get_conn
from portal.routes import subscriptions as routes


def _offre(**extra: Any) -> Offer:
    base: dict[str, Any] = {
        "slug": "standard",
        "label": "Standard",
        "hosting_type": "mutualise",
        "published": True,
        "duration_days": 30,
        "provider_slug": "stripe-fr",
        "prices": [OfferPrice(currency="EUR", amount_minor=1200)],
    }
    base.update(extra)
    return Offer.model_validate(base)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router, prefix="/me")
    app.dependency_overrides[require_user] = lambda: UserInfo(login="bob", roles=["dev"])
    app.dependency_overrides[get_conn] = lambda: None

    etat: dict[str, Any] = {
        "offres": {"standard": _offre()},
        "devise_defaut": "EUR",
        "devises": ["EUR", "USD"],
        "providers_par_pays": {"FR": ["stripe-fr"]},
        "pays": [
            Country(code="FR", label="France"),
            Country(code="BE", label="Belgique", enabled=False),
        ],
        "deja_souscrites": set(),
        "crees": [],
    }

    async def _get_offer(slug: str, _conn: Any) -> Offer | None:
        return etat["offres"].get(slug)

    async def _devise_par_defaut(_conn: Any) -> str | None:
        return etat["devise_defaut"]

    async def _devises_actives(_conn: Any) -> list[str]:
        return list(etat["devises"])

    async def _list_country_providers(
        _conn: Any, *, country_code: str | None = None
    ) -> list[CountryProvider]:
        return [
            CountryProvider(country_code=country_code or "FR", provider_slug=slug)
            for slug in etat["providers_par_pays"].get(country_code, [])
        ]

    async def _list_countries(_conn: Any) -> list[Country]:
        return list(etat["pays"])

    async def _offres_deja_souscrites(login: str, _conn: Any) -> set[str]:
        return set(etat["deja_souscrites"])

    async def _creer(abonnement: Subscription, _conn: Any) -> None:
        etat["crees"].append(abonnement)

    async def _list_de(login: str, _conn: Any) -> list[Subscription]:
        return [s for s in etat["crees"] if s.login == login]

    for nom, impl in {
        "get_offer": _get_offer,
        "devise_par_defaut": _devise_par_defaut,
        "devises_actives": _devises_actives,
        "list_country_providers": _list_country_providers,
        "list_countries": _list_countries,
        "offres_deja_souscrites": _offres_deja_souscrites,
        "creer": _creer,
        "list_de": _list_de,
    }.items():
        monkeypatch.setattr(routes, nom, impl)

    client = TestClient(app)
    client.etat = etat  # type: ignore[attr-defined]
    return client


def _corps(**extra: Any) -> dict[str, Any]:
    return {"offer_slug": "standard", "country_code": "FR", **extra}


# ─── Le cas nominal ──────────────────────────────────────────────────────────


def test_souscrire_cree_un_abonnement(client: TestClient) -> None:
    reponse = client.post("/me/subscriptions", json=_corps())

    assert reponse.status_code == 201
    corps = reponse.json()
    assert corps["offer_slug"] == "standard"
    assert corps["login"] == "bob"
    assert corps["state"] == "essai"
    assert corps["country_code"] == "FR"
    assert corps["currency"] == "EUR"


def test_le_prix_est_un_instantane(client: TestClient) -> None:
    """Le catalogue évoluera ; cet abonné garde le prix auquel il a souscrit."""
    reponse = client.post("/me/subscriptions", json=_corps())

    assert reponse.json()["amount_minor"] == 1200


def test_l_echeance_est_posee_a_la_souscription(client: TestClient) -> None:
    """Tout forfait est borné : sans terme, l'abonnement ne finirait jamais."""
    reponse = client.post("/me/subscriptions", json=_corps())

    assert reponse.json()["ends_at"] is not None


def test_la_devise_par_defaut_s_applique_sans_choix(client: TestClient) -> None:
    reponse = client.post("/me/subscriptions", json=_corps())

    assert reponse.json()["currency"] == "EUR"


def test_le_client_peut_choisir_une_autre_devise(client: TestClient) -> None:
    client.etat["offres"]["standard"] = _offre(  # type: ignore[attr-defined]
        prices=[
            OfferPrice(currency="EUR", amount_minor=1200),
            OfferPrice(currency="USD", amount_minor=1500),
        ]
    )

    reponse = client.post("/me/subscriptions", json=_corps(currency="USD"))

    assert reponse.status_code == 201
    assert reponse.json()["currency"] == "USD"
    assert reponse.json()["amount_minor"] == 1500


# ─── Les refus ───────────────────────────────────────────────────────────────


def test_une_offre_inconnue_rend_404(client: TestClient) -> None:
    assert client.post("/me/subscriptions", json=_corps(offer_slug="fantome")).status_code == 404


def test_une_offre_deja_souscrite_et_unique_est_refusee(client: TestClient) -> None:
    client.etat["offres"]["standard"] = _offre(une_par_compte=True)  # type: ignore[attr-defined]
    client.etat["deja_souscrites"] = {"standard"}  # type: ignore[attr-defined]

    reponse = client.post("/me/subscriptions", json=_corps())

    # 409 et non 400 : la demande est bien formée, c'est l'état du compte qui
    # s'y oppose. Le message est affichable tel quel.
    assert reponse.status_code == 409
    assert "une par compte" in reponse.json()["detail"]


def test_deux_souscriptions_a_une_offre_repetable_passent(client: TestClient) -> None:
    """Le cas qu'une clé d'idempotence trop large avait interdit en silence."""
    client.etat["deja_souscrites"] = {"standard"}  # type: ignore[attr-defined]

    assert client.post("/me/subscriptions", json=_corps()).status_code == 201


def test_un_pays_sans_canal_journalise_la_vente_perdue(client: TestClient) -> None:
    """DoD du ticket « Pays sans canal de paiement » : l'exploitant doit savoir
    que le cas s'est produit. Le client n'y peut rien — c'est un trou de
    configuration — donc la perte doit remonter côté exploitation, pas rester
    subie en silence."""
    import structlog.testing

    with structlog.testing.capture_logs() as journaux:
        reponse = client.post("/me/subscriptions", json=_corps(country_code="BE"))

    assert reponse.status_code == 409
    (entree,) = [j for j in journaux if j["event"] == "vente_perdue_pays_sans_canal"]
    assert entree["offer"] == "standard"
    assert entree["pays"] == "BE"


def test_un_refus_ordinaire_ne_compte_pas_comme_vente_perdue(client: TestClient) -> None:
    """Une offre « une par compte » déjà souscrite est un refus LÉGITIME, pas un
    trou de configuration : le journal de vente perdue ne doit pas s'y déclencher."""
    import structlog.testing

    client.etat["offres"]["standard"] = _offre(une_par_compte=True)  # type: ignore[attr-defined]
    client.etat["deja_souscrites"] = {"standard"}  # type: ignore[attr-defined]

    with structlog.testing.capture_logs() as journaux:
        assert client.post("/me/subscriptions", json=_corps()).status_code == 409

    assert not [j for j in journaux if j["event"] == "vente_perdue_pays_sans_canal"]


def test_un_pays_sans_canal_est_refuse(client: TestClient) -> None:
    """Refus assumé comme provisoire : c'est un trou de configuration."""
    reponse = client.post("/me/subscriptions", json=_corps(country_code="BE"))

    assert reponse.status_code == 409
    assert "BE" in reponse.json()["detail"]


def test_un_code_pays_mal_forme_est_refuse(client: TestClient) -> None:
    assert client.post("/me/subscriptions", json=_corps(country_code="fr")).status_code == 422


def test_aucun_abonnement_n_est_cree_quand_on_refuse(client: TestClient) -> None:
    """Le refus ne doit pas laisser d'abonnement à moitié posé."""
    client.post("/me/subscriptions", json=_corps(country_code="BE"))

    assert client.etat["crees"] == []  # type: ignore[attr-defined]


# ─── L'offre gratuite : le seul parcours complet aujourd'hui ─────────────────


def test_une_offre_gratuite_se_souscrit_sans_prix_ni_canal(client: TestClient) -> None:
    client.etat["offres"]["standard"] = _offre(  # type: ignore[attr-defined]
        is_free=True, prices=[], provider_slug=None
    )
    client.etat["providers_par_pays"] = {}  # type: ignore[attr-defined]

    reponse = client.post("/me/subscriptions", json=_corps())

    assert reponse.status_code == 201
    assert reponse.json()["amount_minor"] == 0
    # Aucun canal à honorer : ne pas en inventer un.
    assert reponse.json()["provider_slug"] is None


# ─── Le contexte de l'écran d'engagement ─────────────────────────────────────


def test_le_contexte_devine_le_pays_depuis_cloudflare(client: TestClient) -> None:
    reponse = client.get("/me/subscriptions/contexte", headers={"CF-IPCountry": "be"})

    assert reponse.json()["pays_devine"] == "BE"


def test_un_pays_inconnu_de_cloudflare_ne_devine_rien(client: TestClient) -> None:
    """`XX` et `T1` sont des réponses de Cloudflare, pas des pays."""
    for valeur in ("XX", "T1", "", "FRA", "1?"):
        reponse = client.get("/me/subscriptions/contexte", headers={"CF-IPCountry": valeur})
        assert reponse.json()["pays_devine"] is None, valeur


def test_sans_en_tete_aucune_deduction(client: TestClient) -> None:
    """Derrière un proxy qui ne transmet rien, on ne devine pas : le client choisit."""
    assert client.get("/me/subscriptions/contexte").json()["pays_devine"] is None


def test_le_contexte_ne_propose_que_les_pays_ouverts(client: TestClient) -> None:
    """Proposer un pays ou l'on ne vend pas menerait droit a un refus."""
    corps = client.get("/me/subscriptions/contexte").json()

    assert [p["code"] for p in corps["pays"]] == ["FR"]


def test_le_contexte_donne_les_devises_acceptees(client: TestClient) -> None:
    corps = client.get("/me/subscriptions/contexte").json()

    assert corps["devise_par_defaut"] == "EUR"
    assert corps["devises"] == ["EUR", "USD"]
