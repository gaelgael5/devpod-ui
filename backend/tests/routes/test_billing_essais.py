"""Essais gratuits offerts par l'admin, vus de l'API.

Un essai offert est adossé à une SOUSCRIPTION de forfait — pas un drapeau sur le
compte. La route en crée une par bénéficiaire, en état `essai`, à montant nul,
et déclenche le même provisioning `debut_essai` qu'une souscription gratuite.

L'appel est en LOT : un refus pour un compte ne doit pas priver les autres.
La réponse dit, compte par compte, ce qui a été accordé et pourquoi le reste
ne l'a pas été.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.auth.rbac import UserInfo, require_admin
from portal.billing.models import Offer
from portal.billing.subscriptions import Subscription, SubscriptionEvent
from portal.db.engine import get_conn
from portal.routes import billing_essais as routes


def _offre(**extra: Any) -> Offer:
    base: dict[str, Any] = {
        "slug": "standard",
        "label": "Standard",
        "hosting_type": "mutualise",
        "published": True,
        "duration_days": 30,
        "host_profiles": ["host-standard"],
    }
    base.update(extra)
    return Offer.model_validate(base)


def _abonnement(**extra: Any) -> Subscription:
    base: dict[str, Any] = {
        "id": "00000000-0000-0000-0000-000000000001",
        "login": "bob",
        "offer_slug": "standard",
        "state": "actif",
        "country_code": "FR",
        "currency": "EUR",
        "amount_minor": 1200,
    }
    base.update(extra)
    return Subscription.model_validate(base)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router, prefix="/admin")
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="root", roles=["admin"])
    app.dependency_overrides[get_conn] = lambda: None

    etat: dict[str, Any] = {
        "offres": {"standard": _offre()},
        "devise_defaut": "EUR",
        "comptes": {"bob", "alice"},
        "abonnements": {},  # login -> list[Subscription]
        "essais_offerts": set(),  # (login, offer_slug)
        "crees": [],
        "evenements": [],
        "provisionnements": [],
    }

    async def _get_offer(slug: str, _conn: Any) -> Offer | None:
        return etat["offres"].get(slug)

    async def _devise_par_defaut(_conn: Any) -> str | None:
        return etat["devise_defaut"]

    async def _user_exists_db(login: str, _conn: Any) -> bool:
        return login in etat["comptes"]

    async def _list_de(login: str, _conn: Any) -> list[Subscription]:
        return list(etat["abonnements"].get(login, []))

    async def _essai_deja_offert(login: str, offer_slug: str, _conn: Any) -> bool:
        return (login, offer_slug) in etat["essais_offerts"]

    async def _creer(abonnement: Subscription, _conn: Any) -> None:
        etat["crees"].append(abonnement)

    async def _enregistrer(
        event: SubscriptionEvent, subscription_id: str | None, _conn: Any
    ) -> bool:
        etat["evenements"].append((event, subscription_id))
        return True

    def _lancer_provisioning(**kwargs: Any) -> None:
        etat["provisionnements"].append(kwargs)

    for nom, impl in {
        "get_offer": _get_offer,
        "devise_par_defaut": _devise_par_defaut,
        "user_exists_db": _user_exists_db,
        "list_de": _list_de,
        "essai_deja_offert": _essai_deja_offert,
        "creer": _creer,
        "enregistrer": _enregistrer,
        "lancer_provisioning": _lancer_provisioning,
    }.items():
        monkeypatch.setattr(routes, nom, impl)

    client = TestClient(app)
    client.etat = etat  # type: ignore[attr-defined]
    return client


def _corps(**extra: Any) -> dict[str, Any]:
    fin = (datetime.now(UTC) + timedelta(days=14)).isoformat()
    return {"offer_slug": "standard", "logins": ["bob"], "fin": fin, **extra}


# ─── Le cas nominal ──────────────────────────────────────────────────────────


def test_un_essai_offert_cree_un_abonnement_en_essai(client: TestClient) -> None:
    reponse = client.post("/admin/billing/essais", json=_corps())

    assert reponse.status_code == 200
    (resultat,) = reponse.json()["resultats"]
    assert resultat["login"] == "bob"
    assert resultat["accorde"] is True
    (cree,) = client.etat["crees"]  # type: ignore[attr-defined]
    assert cree.login == "bob"
    assert cree.offer_slug == "standard"
    assert cree.state == "essai"
    assert resultat["subscription_id"] == cree.id


def test_un_essai_offert_ne_coute_rien(client: TestClient) -> None:
    """Le montant instantané est NUL : c'est un cadeau, pas une vente. La
    conversion en payant passera par une souscription normale, au tarif du jour."""
    client.post("/admin/billing/essais", json=_corps())

    (cree,) = client.etat["crees"]  # type: ignore[attr-defined]
    assert cree.amount_minor == 0
    assert cree.provider_slug is None


def test_l_essai_s_arrete_a_la_date_choisie(client: TestClient) -> None:
    fin = datetime.now(UTC) + timedelta(days=7)
    client.post("/admin/billing/essais", json=_corps(fin=fin.isoformat()))

    (cree,) = client.etat["crees"]  # type: ignore[attr-defined]
    assert cree.trial_end == fin
    assert cree.ends_at == fin


def test_le_pays_vient_du_dernier_abonnement_du_compte(client: TestClient) -> None:
    client.etat["abonnements"]["bob"] = [  # type: ignore[attr-defined]
        _abonnement(state="resilie", country_code="BE", offer_slug="ancienne")
    ]

    client.post("/admin/billing/essais", json=_corps())

    (cree,) = client.etat["crees"]  # type: ignore[attr-defined]
    assert cree.country_code == "BE"


def test_sans_historique_le_pays_est_inconnu(client: TestClient) -> None:
    """`ZZ` (ISO 3166, plage à usage privé) : on ne devine pas un pays — la
    conversion en payant le demandera au client, comme toute souscription."""
    client.post("/admin/billing/essais", json=_corps())

    (cree,) = client.etat["crees"]  # type: ignore[attr-defined]
    assert cree.country_code == "ZZ"


def test_l_essai_declenche_le_provisioning_debut_essai(client: TestClient) -> None:
    client.post("/admin/billing/essais", json=_corps())

    (lance,) = client.etat["provisionnements"]  # type: ignore[attr-defined]
    (cree,) = client.etat["crees"]  # type: ignore[attr-defined]
    assert lance["evenement"] == "debut_essai"
    assert lance["subscription_id"] == cree.id
    assert lance["provider_event_id"] == f"essai_admin:{cree.id}"
    assert lance["host_profiles"] == ["host-standard"]


def test_l_essai_se_journalise_dans_l_historique(client: TestClient) -> None:
    """L'entrée porte le login ET l'abonnement : l'utilisateur la voit dans SON
    historique (visibilité `achat` par défaut), l'admin la retrouve au global."""
    client.post("/admin/billing/essais", json=_corps())

    ((event, subscription_id),) = client.etat["evenements"]  # type: ignore[attr-defined]
    (cree,) = client.etat["crees"]  # type: ignore[attr-defined]
    assert event.kind == "debut_essai"
    assert event.provider_slug == "portail"
    assert event.provider_event_id == f"essai_admin:{cree.id}"
    assert event.login == "bob"
    assert subscription_id == cree.id


def test_le_lot_traite_chaque_compte_independamment(client: TestClient) -> None:
    """Un refus pour un compte ne prive pas les autres : c'est le sens du lot."""
    reponse = client.post("/admin/billing/essais", json=_corps(logins=["bob", "fantome", "alice"]))

    corps = reponse.json()["resultats"]
    assert [(r["login"], r["accorde"]) for r in corps] == [
        ("bob", True),
        ("fantome", False),
        ("alice", True),
    ]
    assert len(client.etat["crees"]) == 2  # type: ignore[attr-defined]


# ─── Les refus ───────────────────────────────────────────────────────────────


def test_une_offre_inconnue_rend_404(client: TestClient) -> None:
    assert (
        client.post("/admin/billing/essais", json=_corps(offer_slug="fantome")).status_code == 404
    )


def test_une_fin_passee_est_refusee(client: TestClient) -> None:
    hier = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    reponse = client.post("/admin/billing/essais", json=_corps(fin=hier))

    assert reponse.status_code == 422
    assert client.etat["crees"] == []  # type: ignore[attr-defined]


def test_sans_devise_configuree_le_catalogue_n_est_pas_pret(client: TestClient) -> None:
    client.etat["devise_defaut"] = None  # type: ignore[attr-defined]

    assert client.post("/admin/billing/essais", json=_corps()).status_code == 409


def test_un_compte_inconnu_est_refuse_sans_bloquer_le_lot(client: TestClient) -> None:
    reponse = client.post("/admin/billing/essais", json=_corps(logins=["fantome"]))

    (resultat,) = reponse.json()["resultats"]
    assert resultat["accorde"] is False
    assert "inconnu" in resultat["motif"]
    assert client.etat["crees"] == []  # type: ignore[attr-defined]


def test_un_abonnement_en_cours_sur_l_offre_refuse_l_essai(client: TestClient) -> None:
    """Offrir un essai d'une offre que le compte PAIE déjà n'a pas de sens — et
    le provisioning n'y verrait qu'un rejeu. On refuse, avec le motif."""
    client.etat["abonnements"]["bob"] = [_abonnement()]  # type: ignore[attr-defined]

    reponse = client.post("/admin/billing/essais", json=_corps())

    (resultat,) = reponse.json()["resultats"]
    assert resultat["accorde"] is False
    assert "en cours" in resultat["motif"]


def test_un_abonnement_resilie_ne_bloque_pas_l_essai(client: TestClient) -> None:
    """Le scénario de RÉTENTION : un ancien abonné parti se voit offrir un
    essai pour revenir. Son abonnement clos ne s'y oppose pas."""
    client.etat["abonnements"]["bob"] = [_abonnement(state="resilie")]  # type: ignore[attr-defined]

    reponse = client.post("/admin/billing/essais", json=_corps())

    (resultat,) = reponse.json()["resultats"]
    assert resultat["accorde"] is True


def test_un_essai_deja_offert_ne_se_reoffre_pas(client: TestClient) -> None:
    """Le garde-fou anti-abus, assis sur l'HISTORIQUE : un compte ne cumule pas
    les essais offerts sur la même offre — sinon l'essai gratuit se renouvelle
    indéfiniment à coups de gestes admin."""
    client.etat["essais_offerts"] = {("bob", "standard")}  # type: ignore[attr-defined]

    reponse = client.post("/admin/billing/essais", json=_corps())

    (resultat,) = reponse.json()["resultats"]
    assert resultat["accorde"] is False
    assert "déjà bénéficié" in resultat["motif"]
    assert client.etat["crees"] == []  # type: ignore[attr-defined]


def test_aucun_login_est_refuse(client: TestClient) -> None:
    assert client.post("/admin/billing/essais", json=_corps(logins=[])).status_code == 422
