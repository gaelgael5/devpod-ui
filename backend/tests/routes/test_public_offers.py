"""Offres servies SANS authentification, pour la page publique des forfaits.

Deux invariants gouvernent ce fichier, et ils ne disent pas la même chose :

- **une offre non publiée n'est servie à personne.** C'est un brouillon, ou une
  offre retirée du catalogue ; la servir la rendrait souscriptible par quiconque
  en devine l'existence.
- **la réponse est une liste blanche.** Le modèle `Offer` porte aussi le gabarit
  de VM, la capacité des hosts, le canal de paiement et les profils de host. Sur
  une page ouverte à tous, ces champs sont de l'infrastructure publiée.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.billing.models import Offer, OfferPrice
from portal.config.models import HostProfile
from portal.db.engine import get_conn
from portal.routes import billing_offers

#: Le contrat public, au champ près. Ce jeu est ce qui rend le test utile : une
#: colonne ajoutée à `Offer` et recopiée par inadvertance dans la vue publique
#: casse ce test au lieu de fuiter en silence.
CHAMPS_PUBLICS = {
    "slug",
    "titles",
    "descriptions",
    "hosting_type",
    "max_workspaces",
    "max_hosts_dedies",
    "is_free",
    "duration_days",
    "tacite_reconduction",
    "une_par_compte",
    "currency",
    "amount_minor",
    "prices_include_tax",
}


def _offre(**extra: Any) -> Offer:
    base: dict[str, Any] = {
        "slug": "standard",
        "label": "Standard",
        "titles": {"fr": "Standard", "en": "Standard"},
        "descriptions": {"fr": "Pour commencer", "en": "To get started"},
        "hosting_type": "mutualise",
        "max_workspaces": 3,
        "published": True,
        "duration_days": 30,
        "prices": [OfferPrice(currency="EUR", amount_minor=1200)],
        # Infrastructure : ne doit JAMAIS sortir par la route publique.
        "variables": {"vm_template": "9001", "capacity": "12"},
        "provider_slug": "stripe-fr",
        "host_profiles": ["host-standard"],
    }
    base.update(extra)
    return Offer.model_validate(base)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(billing_offers.router_public)
    app.dependency_overrides[get_conn] = lambda: None

    etat: dict[str, Any] = {"offres": [], "devise": "EUR", "profils": {}}

    async def _list_offers(_conn: Any, *, published_only: bool = False) -> list[Offer]:
        tout = list(etat["offres"])
        return [o for o in tout if o.published] if published_only else tout

    async def _devise_par_defaut(_conn: Any) -> str | None:
        return etat["devise"]

    async def _get_host_profile(slug: str, _conn: Any) -> HostProfile | None:
        return etat["profils"].get(slug)

    monkeypatch.setattr(billing_offers, "list_offers", _list_offers)
    monkeypatch.setattr(billing_offers, "devise_par_defaut", _devise_par_defaut)
    monkeypatch.setattr(billing_offers, "get_host_profile", _get_host_profile)

    client = TestClient(app)
    client.etat = etat  # type: ignore[attr-defined]
    return client


def test_sert_les_offres_publiees_sans_authentification(client: TestClient) -> None:
    client.etat["offres"] = [_offre()]  # type: ignore[attr-defined]

    reponse = client.get("/offers")

    assert reponse.status_code == 200
    (offre,) = reponse.json()
    assert offre["slug"] == "standard"
    assert offre["currency"] == "EUR"
    assert offre["amount_minor"] == 1200


def test_une_offre_non_publiee_n_est_pas_servie(client: TestClient) -> None:
    client.etat["offres"] = [  # type: ignore[attr-defined]
        _offre(slug="brouillon", published=False),
        _offre(slug="standard"),
    ]

    corps = client.get("/offers").json()

    assert [o["slug"] for o in corps] == ["standard"]


def test_aucun_champ_hors_liste_blanche(client: TestClient) -> None:
    """Le test qui compte : la réponse ne porte QUE le contrat public."""
    client.etat["offres"] = [_offre()]  # type: ignore[attr-defined]

    (offre,) = client.get("/offers").json()

    assert set(offre) == CHAMPS_PUBLICS


def test_l_infrastructure_ne_fuit_pas(client: TestClient) -> None:
    """Explicite sur les champs sensibles, pour que l'intention reste lisible."""
    client.etat["offres"] = [_offre()]  # type: ignore[attr-defined]

    corps = client.get("/offers").text

    for interdit in ("variables", "vm_template", "provider_slug", "stripe-fr", "host_profiles"):
        assert interdit not in corps


def _profil(slug: str, capacite: str | None) -> HostProfile:
    variables = {} if capacite is None else {"capacity_workspaces": capacite}
    return HostProfile(slug=slug, label=slug, machine_profile="mp-std", variables=variables)


class TestPlafondDedie:
    """En dédié, « illimité » n'existe pas : une machine a une capacité.

    Le plafond affiché est le plafond OPPOSABLE, celui de `limite_effective` :
    min(capacité déclarée par le profil de host, quota commercial de l'offre).
    Quand rien n'est déclaré, la réponse est `null` — « non renseigné », que la
    page n'a pas le droit de lire « illimité ».
    """

    def test_la_capacite_vient_du_profil_de_host(self, client: TestClient) -> None:
        client.etat["profils"] = {"h1": _profil("h1", "8")}  # type: ignore[attr-defined]
        client.etat["offres"] = [  # type: ignore[attr-defined]
            _offre(hosting_type="dedie", max_workspaces=None, host_profiles=["h1"])
        ]

        (offre,) = client.get("/offers").json()

        assert offre["max_workspaces"] == 8

    def test_le_quota_de_l_offre_prime_s_il_est_plus_bas(self, client: TestClient) -> None:
        client.etat["profils"] = {"h1": _profil("h1", "8")}  # type: ignore[attr-defined]
        client.etat["offres"] = [  # type: ignore[attr-defined]
            _offre(hosting_type="dedie", max_workspaces=5, host_profiles=["h1"])
        ]

        (offre,) = client.get("/offers").json()

        assert offre["max_workspaces"] == 5

    def test_la_capacite_prime_sur_un_quota_plus_haut(self, client: TestClient) -> None:
        client.etat["profils"] = {"h1": _profil("h1", "8")}  # type: ignore[attr-defined]
        client.etat["offres"] = [  # type: ignore[attr-defined]
            _offre(hosting_type="dedie", max_workspaces=20, host_profiles=["h1"])
        ]

        (offre,) = client.get("/offers").json()

        assert offre["max_workspaces"] == 8

    def test_plusieurs_profils_le_plancher_fait_foi(self, client: TestClient) -> None:
        """Le provisioning peut retomber sur n'importe quel profil de la liste :
        on promet ce que le moins capable garantit, pas ce que le meilleur offre."""
        client.etat["profils"] = {  # type: ignore[attr-defined]
            "h1": _profil("h1", "10"),
            "h2": _profil("h2", "8"),
        }
        client.etat["offres"] = [  # type: ignore[attr-defined]
            _offre(hosting_type="dedie", max_workspaces=None, host_profiles=["h1", "h2"])
        ]

        (offre,) = client.get("/offers").json()

        assert offre["max_workspaces"] == 8

    def test_aucune_capacite_declaree_rend_null_pas_illimite(self, client: TestClient) -> None:
        client.etat["profils"] = {"h1": _profil("h1", None)}  # type: ignore[attr-defined]
        client.etat["offres"] = [  # type: ignore[attr-defined]
            _offre(hosting_type="dedie", max_workspaces=None, host_profiles=["h1"])
        ]

        (offre,) = client.get("/offers").json()

        assert offre["max_workspaces"] is None

    def test_le_mutualise_ne_consulte_pas_les_profils(self, client: TestClient) -> None:
        """En mutualisé, `max_workspaces` est le quota personnel du souscripteur,
        pas la capacité d'une machine : le profil de host n'a rien à y dire."""
        client.etat["profils"] = {"h1": _profil("h1", "8")}  # type: ignore[attr-defined]
        client.etat["offres"] = [  # type: ignore[attr-defined]
            _offre(hosting_type="mutualise", max_workspaces=None, host_profiles=["h1"])
        ]

        (offre,) = client.get("/offers").json()

        assert offre["max_workspaces"] is None


def test_offre_gratuite_sans_prix(client: TestClient) -> None:
    """Une offre gratuite se lit sur `is_free`, jamais sur un montant nul."""
    client.etat["offres"] = [_offre(is_free=True, prices=[])]  # type: ignore[attr-defined]

    (offre,) = client.get("/offers").json()

    assert offre["is_free"] is True
    assert offre["amount_minor"] is None


def test_offre_sans_prix_dans_la_devise_par_defaut(client: TestClient) -> None:
    """Pas de conversion depuis une autre devise : on affiche sans prix.

    Convertir à un taux flottant ferait diverger l'affiché du débité.
    """
    client.etat["offres"] = [  # type: ignore[attr-defined]
        _offre(prices=[OfferPrice(currency="USD", amount_minor=1500)])
    ]

    (offre,) = client.get("/offers").json()

    assert offre["currency"] == "EUR"
    assert offre["amount_minor"] is None


def test_aucune_devise_par_defaut_designee(client: TestClient) -> None:
    """Trou de configuration : la page s'affiche, sans prix — elle ne casse pas."""
    client.etat["devise"] = None  # type: ignore[attr-defined]
    client.etat["offres"] = [_offre()]  # type: ignore[attr-defined]

    (offre,) = client.get("/offers").json()

    assert offre["currency"] is None
    assert offre["amount_minor"] is None
