"""Ouverture de la page de paiement d'un abonnement.

Le test qui compte ici est celui de l'APPARTENANCE : la route prend un
identifiant dans l'URL, et rien dans un UUID n'empêche d'en demander un autre.
Une revue de sécurité de ce dépôt a déjà trouvé une route qui lisait un
identifiant sans le corréler à son propriétaire ; celle-ci ne doit pas rejouer
la même faute.

Le reste porte sur les refus : un abonnement déjà payé, une offre gratuite, un
canal absent ou désactivé. Aucun ne doit ouvrir une page de paiement.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.auth.rbac import UserInfo, require_user
from portal.billing.canal import DemandePaiement, PaiementImpossible
from portal.billing.models import Offer, PaymentProvider
from portal.billing.subscriptions import Subscription
from portal.db.engine import get_conn
from portal.routes import subscriptions as routes

ABO_ID = "11111111-1111-1111-1111-111111111111"


def _abonnement(**extra: Any) -> Subscription:
    base: dict[str, Any] = {
        "id": ABO_ID,
        "login": "alice",
        "offer_slug": "standard",
        "provider_slug": "stripe-fr",
        "state": "essai",
        "country_code": "FR",
        "currency": "EUR",
        "amount_minor": 1200,
    }
    base.update(extra)
    return Subscription.model_validate(base)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router, prefix="/me")
    app.dependency_overrides[get_conn] = lambda: None
    app.dependency_overrides[require_user] = lambda: UserInfo(login="alice", roles=["dev"])

    etat: dict[str, Any] = {
        "abonnement": _abonnement(),
        "offre": Offer(
            slug="standard",
            label="Standard",
            duration_days=30,
            tacite_reconduction=True,
            provider_slug="stripe-fr",
        ),
        "provider": PaymentProvider(slug="stripe-fr", label="Stripe FR", kind="stripe"),
        "cle": "sk_test_doublure",
        "url": "https://paiement/cs_1",
        "echec": None,
        "demandes": [],
    }

    class _CanalTemoin:
        kind = "stripe"

        async def ouvrir_paiement(self, demande: DemandePaiement, cle_api: str) -> str:
            if etat["echec"]:
                raise PaiementImpossible(str(etat["echec"]))
            etat["demandes"].append((demande, cle_api))
            return str(etat["url"])

    async def _get(sid: str, _conn: Any) -> Subscription | None:
        abo = etat["abonnement"]
        return abo if abo and abo.id == sid else None

    async def _get_offer(slug: str, _conn: Any) -> Offer | None:
        offre = etat["offre"]
        return offre if offre and offre.slug == slug else None

    async def _get_provider(slug: str, _conn: Any) -> PaymentProvider | None:
        p = etat["provider"]
        return p if p and p.slug == slug else None

    async def _reveal(slug: str, _conn: Any) -> str:
        if not etat["cle"]:
            raise RuntimeError("secret absent")
        return str(etat["cle"])

    async def _email(login: str, _conn: Any) -> str:
        return "alice@example.org"

    async def _adresse_figee(subscription_id: str, _conn: Any) -> None:
        return None

    for nom, impl in {
        "get": _get,
        "get_offer": _get_offer,
        "get_provider": _get_provider,
        "reveal_system_secret": _reveal,
        "email_de": _email,
        "adresse_figee": _adresse_figee,
    }.items():
        monkeypatch.setattr(routes, nom, impl)
    monkeypatch.setattr(routes, "CANAUX", {"stripe": _CanalTemoin()})

    class _Serveur:
        external_url = "https://portail.example/"

    monkeypatch.setattr(routes, "load_global", lambda: type("C", (), {"server": _Serveur()})())

    client = TestClient(app)
    client.etat = etat  # type: ignore[attr-defined]
    return client


def _ouvrir(client: TestClient, sid: str = ABO_ID) -> Any:
    return client.post(f"/me/subscriptions/{sid}/paiement")


# ─── Appartenance ────────────────────────────────────────────────────────────


def test_l_abonnement_d_un_autre_est_introuvable(client: TestClient) -> None:
    """LE test de cette route. Un UUID valide n'autorise pas à le réclamer."""
    client.etat["abonnement"] = _abonnement(login="bob")  # type: ignore[attr-defined]

    reponse = _ouvrir(client)

    assert reponse.status_code == 404
    # Aucune session ouverte : on n'a pas fait payer alice pour bob.
    assert client.etat["demandes"] == []  # type: ignore[attr-defined]


def test_un_abonnement_inexistant_rend_le_meme_404(client: TestClient) -> None:
    """Même réponse que « pas à vous » : distinguer dirait quels ids existent."""
    autre = "22222222-2222-2222-2222-222222222222"

    assert _ouvrir(client, autre).status_code == 404


# ─── Ce qui n'ouvre pas de paiement ──────────────────────────────────────────


def test_un_abonnement_deja_actif_est_refuse(client: TestClient) -> None:
    client.etat["abonnement"] = _abonnement(state="actif")  # type: ignore[attr-defined]

    assert _ouvrir(client).status_code == 409


def test_un_abonnement_resilie_est_refuse(client: TestClient) -> None:
    client.etat["abonnement"] = _abonnement(state="resilie")  # type: ignore[attr-defined]

    assert _ouvrir(client).status_code == 409


def test_apres_un_echec_de_paiement_on_peut_reprendre(client: TestClient) -> None:
    """Une carte refusée ne doit pas obliger à re-souscrire."""
    client.etat["abonnement"] = _abonnement(state="echec_paiement")  # type: ignore[attr-defined]

    assert _ouvrir(client).status_code == 200


def test_une_offre_gratuite_n_a_rien_a_payer(client: TestClient) -> None:
    client.etat["offre"] = client.etat["offre"].model_copy(  # type: ignore[attr-defined]
        update={"is_free": True}
    )

    assert _ouvrir(client).status_code == 409


def test_sans_canal_configure_on_refuse(client: TestClient) -> None:
    client.etat["provider"] = None  # type: ignore[attr-defined]

    assert _ouvrir(client).status_code == 409


def test_un_canal_desactive_n_ouvre_rien(client: TestClient) -> None:
    client.etat["provider"] = PaymentProvider(  # type: ignore[attr-defined]
        slug="stripe-fr", label="Stripe FR", kind="stripe", enabled=False
    )

    assert _ouvrir(client).status_code == 409


def test_sans_clef_lisible_on_refuse(client: TestClient) -> None:
    client.etat["cle"] = ""  # type: ignore[attr-defined]

    assert _ouvrir(client).status_code == 409


def test_un_refus_du_canal_remonte_en_502_sans_son_motif(client: TestClient) -> None:
    """Le motif décrit NOTRE requête : l'utilisateur n'a rien à en faire."""
    client.etat["echec"] = "montant invalide pour la devise"  # type: ignore[attr-defined]

    reponse = _ouvrir(client)

    assert reponse.status_code == 502
    assert "montant invalide" not in reponse.json()["detail"]


# ─── Ce qui part au canal ────────────────────────────────────────────────────


def test_l_url_de_paiement_est_rendue(client: TestClient) -> None:
    reponse = _ouvrir(client)

    assert reponse.status_code == 200
    assert reponse.json() == {"url": "https://paiement/cs_1"}


def test_le_montant_est_l_instantane_de_l_abonnement(client: TestClient) -> None:
    """Le catalogue a pu changer depuis la souscription. L'abonné garde son prix."""
    client.etat["abonnement"] = _abonnement(amount_minor=990)  # type: ignore[attr-defined]

    _ouvrir(client)

    ((demande, _),) = client.etat["demandes"]  # type: ignore[attr-defined]
    assert demande.montant_minor == 990


def test_les_urls_de_retour_sont_absolues(client: TestClient) -> None:
    """Le fournisseur redirige un navigateur : un chemin relatif ne mène nulle part."""
    _ouvrir(client)

    ((demande, _),) = client.etat["demandes"]  # type: ignore[attr-defined]
    assert demande.url_succes.startswith("https://portail.example/")
    assert demande.url_abandon.startswith("https://portail.example/")
    # Pas de double slash : `external_url` peut finir par un séparateur.
    assert "//forfaits" not in demande.url_succes + demande.url_abandon
