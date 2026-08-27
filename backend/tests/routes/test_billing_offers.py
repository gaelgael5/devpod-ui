"""API des taux de taxe et des offres d'abonnement.

Deux règles structurent ce fichier :

- un taux de taxe est HISTORISÉ, jamais écrasé — une facture émise l'an dernier
  doit rester reproductible avec le taux de l'époque ;
- une offre publiée est une offre qu'on peut réellement vendre — sans prix dans
  une devise activée, elle ne l'est pas.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.auth.rbac import UserInfo, require_admin
from portal.billing.models import Country, Offer, TaxRate
from portal.db.engine import get_conn
from portal.routes import billing_offers

HIER = date.today() - timedelta(days=365)
DEMAIN = date.today() + timedelta(days=1)


class _Store:
    def __init__(self) -> None:
        self.pays: dict[str, Country] = {"FR": Country(code="FR", label="France")}
        self.devises_actives: list[str] = ["EUR"]
        self.taux: dict[int, TaxRate] = {}
        self.offres: dict[str, Offer] = {}
        self.providers: set[str] = {"stripe-fr"}
        self.offres_referencees: set[str] = set()
        self._seq = 0

    def ajoute_taux(self, taux: TaxRate) -> TaxRate:
        self._seq += 1
        pose = taux.model_copy(update={"id": self._seq})
        self.taux[self._seq] = pose
        return pose


@pytest.fixture
def store() -> _Store:
    return _Store()


@pytest.fixture
def client(store: _Store, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(billing_offers.router, prefix="/admin")
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="admin", roles=["admin"])
    app.dependency_overrides[get_conn] = lambda: None

    async def _get_country(code: str, _conn: Any) -> Country | None:
        return store.pays.get(code)

    async def _devises_actives(_conn: Any) -> list[str]:
        return list(store.devises_actives)

    async def _list_tax_rates(_conn: Any, *, country_code: str | None = None) -> list[TaxRate]:
        tous = list(store.taux.values())
        if country_code is not None:
            tous = [t for t in tous if t.country_code == country_code]
        return sorted(tous, key=lambda t: t.valid_from)

    async def _get_tax_rate(rate_id: int, _conn: Any) -> TaxRate | None:
        return store.taux.get(rate_id)

    async def _add_tax_rate(taux: TaxRate, _conn: Any) -> TaxRate:
        return store.ajoute_taux(taux)

    async def _close_tax_rate(rate_id: int, valid_to: date, _conn: Any) -> bool:
        courant = store.taux.get(rate_id)
        if courant is None:
            return False
        store.taux[rate_id] = courant.model_copy(update={"valid_to": valid_to})
        return True

    async def _delete_tax_rate(rate_id: int, _conn: Any) -> bool:
        return store.taux.pop(rate_id, None) is not None

    async def _list_offers(_conn: Any, *, published_only: bool = False) -> list[Offer]:
        tout = list(store.offres.values())
        return [o for o in tout if o.published] if published_only else tout

    async def _get_offer(slug: str, _conn: Any) -> Offer | None:
        return store.offres.get(slug)

    async def _upsert_offer(offre: Offer, _conn: Any) -> None:
        store.offres[offre.slug] = offre

    async def _delete_offer(slug: str, _conn: Any) -> bool:
        return store.offres.pop(slug, None) is not None

    async def _offer_reference(slug: str, _conn: Any) -> bool:
        return slug in store.offres_referencees

    async def _get_provider(slug: str, _conn: Any) -> Any:
        return object() if slug in store.providers else None

    for nom, impl in {
        "get_country": _get_country,
        "devises_actives": _devises_actives,
        "list_tax_rates": _list_tax_rates,
        "get_tax_rate": _get_tax_rate,
        "add_tax_rate": _add_tax_rate,
        "close_tax_rate": _close_tax_rate,
        "delete_tax_rate": _delete_tax_rate,
        "list_offers": _list_offers,
        "get_offer": _get_offer,
        "upsert_offer": _upsert_offer,
        "delete_offer": _delete_offer,
        "offer_reference": _offer_reference,
        "get_provider": _get_provider,
    }.items():
        monkeypatch.setattr(billing_offers, nom, impl)
    return TestClient(app)


def _taux(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "country_code": "FR",
        "region": "",
        "rate": "0.2000",
        "label": "TVA 20 %",
        "valid_from": HIER.isoformat(),
    }
    base.update(extra)
    return base


# ─── Taux de taxe ────────────────────────────────────────────────────────────


def test_ajoute_un_taux(client: TestClient, store: _Store) -> None:
    res = client.post("/admin/billing/countries/FR/tax-rates", json=_taux())

    assert res.status_code == 201
    assert res.json()["id"] == 1
    assert str(store.taux[1].rate) == "0.2000"


def test_un_taux_sur_un_pays_inconnu_est_un_404(client: TestClient) -> None:
    res = client.post("/admin/billing/countries/ZZ/tax-rates", json=_taux(country_code="ZZ"))

    assert res.status_code == 404


def test_refuse_un_chevauchement_de_periode(client: TestClient, store: _Store) -> None:
    # Deux taux nationaux en vigueur le même jour rendraient le calcul ambigu.
    client.post("/admin/billing/countries/FR/tax-rates", json=_taux())

    res = client.post("/admin/billing/countries/FR/tax-rates", json=_taux(label="TVA bis"))

    assert res.status_code == 409
    assert len(store.taux) == 1


def test_un_taux_regional_peut_coexister_avec_le_national(client: TestClient) -> None:
    # Le plus spécifique gagne : ce n'est pas une ambiguïté, c'est la règle.
    client.post("/admin/billing/countries/FR/tax-rates", json=_taux())

    res = client.post(
        "/admin/billing/countries/FR/tax-rates",
        json=_taux(region="COR", rate="0.1000", label="TVA Corse"),
    )

    assert res.status_code == 201


def test_un_taux_clos_laisse_la_place_au_suivant(client: TestClient) -> None:
    client.post("/admin/billing/countries/FR/tax-rates", json=_taux())
    client.post("/admin/billing/tax-rates/1/close", json={"valid_to": DEMAIN.isoformat()})

    res = client.post(
        "/admin/billing/countries/FR/tax-rates",
        json=_taux(rate="0.2100", label="TVA 21 %", valid_from=DEMAIN.isoformat()),
    )

    assert res.status_code == 201


def test_clore_un_taux_pose_sa_fin(client: TestClient, store: _Store) -> None:
    client.post("/admin/billing/countries/FR/tax-rates", json=_taux())

    res = client.post("/admin/billing/tax-rates/1/close", json={"valid_to": DEMAIN.isoformat()})

    assert res.status_code == 200
    assert store.taux[1].valid_to == DEMAIN


def test_refuse_une_fin_anterieure_au_debut(client: TestClient) -> None:
    client.post("/admin/billing/countries/FR/tax-rates", json=_taux())

    res = client.post(
        "/admin/billing/tax-rates/1/close",
        json={"valid_to": (HIER - timedelta(days=1)).isoformat()},
    )

    assert res.status_code == 422


def test_refuse_de_supprimer_un_taux_deja_en_vigueur(client: TestClient, store: _Store) -> None:
    # Il a pu servir à une facture : on le clôt, on ne l'efface pas.
    client.post("/admin/billing/countries/FR/tax-rates", json=_taux())

    res = client.delete("/admin/billing/tax-rates/1")

    assert res.status_code == 409
    assert 1 in store.taux


def test_supprime_un_taux_futur(client: TestClient, store: _Store) -> None:
    # Celui-là n'a rien pu facturer : c'est une saisie, elle se corrige.
    client.post("/admin/billing/countries/FR/tax-rates", json=_taux(valid_from=DEMAIN.isoformat()))

    assert client.delete("/admin/billing/tax-rates/1").status_code == 204
    assert store.taux == {}


# ─── Offres ──────────────────────────────────────────────────────────────────


def _offre(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "slug": "solo",
        "labels": {"fr": "Solo"},
        "hosting_type": "mutualise",
        "max_workspaces": 3,
        "provider_slug": "stripe-fr",
        "published": False,
        "prices": [{"currency": "EUR", "amount_minor": 1200}],
    }
    base.update(extra)
    return base


def test_cree_une_offre_avec_ses_prix(client: TestClient, store: _Store) -> None:
    res = client.put("/admin/billing/offers/solo", json=_offre())

    assert res.status_code == 200
    assert store.offres["solo"].prix("EUR").amount_minor == 1200


def test_le_slug_de_l_url_fait_foi(client: TestClient, store: _Store) -> None:
    res = client.put("/admin/billing/offers/solo", json=_offre(slug="team"))

    assert res.status_code == 422
    assert store.offres == {}


def test_refuse_deux_prix_dans_la_meme_devise(client: TestClient) -> None:
    res = client.put(
        "/admin/billing/offers/solo",
        json=_offre(
            prices=[
                {"currency": "EUR", "amount_minor": 1200},
                {"currency": "EUR", "amount_minor": 1500},
            ]
        ),
    )

    assert res.status_code == 422


def test_refuse_un_provider_inconnu(client: TestClient) -> None:
    res = client.put("/admin/billing/offers/solo", json=_offre(provider_slug="paypal"))

    assert res.status_code == 422
    assert "paypal" in res.json()["detail"]


def test_refuse_de_publier_une_offre_sans_prix_vendable(client: TestClient) -> None:
    # EUR est la seule devise activée : une offre en USD seul n'est proposable
    # à personne.
    res = client.put(
        "/admin/billing/offers/solo",
        json=_offre(published=True, prices=[{"currency": "USD", "amount_minor": 1200}]),
    )

    assert res.status_code == 422
    assert "EUR" in res.json()["detail"]


def test_publie_une_offre_qui_a_le_prix_requis(client: TestClient, store: _Store) -> None:
    res = client.put("/admin/billing/offers/solo", json=_offre(published=True))

    assert res.status_code == 200
    assert store.offres["solo"].published is True


def test_signale_les_devises_manquantes_sans_bloquer(client: TestClient, store: _Store) -> None:
    # L'offre est vendable en EUR, donc publiable. Mais elle n'a pas de prix en
    # USD : l'absence doit se voir à la saisie plutôt que dans une page vide
    # côté client — signalée, sans bloquer une publication légitime.
    store.devises_actives = ["EUR", "USD"]

    res = client.put("/admin/billing/offers/solo", json=_offre(published=True))

    assert res.status_code == 200
    assert res.json()["devises_manquantes"] == ["USD"]


def test_liste_les_offres_publiees_seulement_sur_demande(client: TestClient) -> None:
    client.put("/admin/billing/offers/solo", json=_offre(published=True))
    client.put("/admin/billing/offers/team", json=_offre(slug="team", published=False))

    tout = client.get("/admin/billing/offers").json()
    publiees = client.get("/admin/billing/offers?published_only=true").json()

    assert {o["slug"] for o in tout} == {"solo", "team"}
    assert {o["slug"] for o in publiees} == {"solo"}


def test_une_offre_inconnue_est_un_404(client: TestClient) -> None:
    assert client.get("/admin/billing/offers/fantome").status_code == 404


def test_refuse_de_supprimer_une_offre_souscrite(client: TestClient, store: _Store) -> None:
    client.put("/admin/billing/offers/solo", json=_offre())
    store.offres_referencees.add("solo")

    res = client.delete("/admin/billing/offers/solo")

    assert res.status_code == 409
    assert "solo" in store.offres


def test_supprime_une_offre_libre(client: TestClient, store: _Store) -> None:
    client.put("/admin/billing/offers/solo", json=_offre())

    assert client.delete("/admin/billing/offers/solo").status_code == 204
    assert store.offres == {}
