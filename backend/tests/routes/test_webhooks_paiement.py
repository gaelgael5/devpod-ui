"""Réception d'un webhook de canal de vente.

C'est une route NON AUTHENTIFIÉE : sa seule protection est la signature. Ces
tests portent donc autant sur ce qu'elle refuse que sur ce qu'elle applique.

Deux comportements méritent d'être compris avant de les lire :

- **on répond 200 à ce qu'on ignore.** Un événement inconnu ou orphelin n'est
  pas une erreur de l'appelant. Rendre une erreur ferait réessayer le
  fournisseur indéfiniment, puis désactiver le point de terminaison — et l'on
  perdrait les événements suivants, ceux qui comptent.
- **l'idempotence est tranchée par l'écriture du journal**, pas par une lecture
  préalable : deux réémissions arrivent souvent en rafale.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portal.billing.models import PaymentProvider
from portal.billing.subscriptions import Subscription, SubscriptionEvent
from portal.db.engine import get_conn
from portal.routes import webhooks_paiement as routes

SECRET = "whsec_de_test"
ABO_ID = "11111111-1111-1111-1111-111111111111"


def _signer(corps: bytes, secret: str = SECRET) -> str:
    horodatage = int(datetime.now(UTC).timestamp())
    signature = hmac.new(
        secret.encode(), f"{horodatage}.".encode() + corps, hashlib.sha256
    ).hexdigest()
    return f"t={horodatage},v1={signature}"


def _abonnement(**extra: Any) -> Subscription:
    base: dict[str, Any] = {
        "id": ABO_ID,
        "login": "alice",
        "offer_slug": "standard",
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
    app.include_router(routes.router)
    app.dependency_overrides[get_conn] = lambda: None

    etat: dict[str, Any] = {
        "provider": PaymentProvider(
            slug="stripe-fr",
            label="Stripe FR",
            kind="stripe",
            config={"webhook_secret_slug": "stripe-whsec"},
        ),
        "secret": SECRET,
        "abonnements": {ABO_ID: _abonnement()},
        "vus": set(),
        "journal": [],
        "etats": [],
    }

    async def _get_provider(slug: str, _conn: Any) -> PaymentProvider | None:
        p = etat["provider"]
        return p if p and p.slug == slug else None

    async def _reveal(slug: str, _conn: Any) -> str:
        if not etat["secret"]:
            raise RuntimeError("secret absent")
        return str(etat["secret"])

    async def _enregistrer(
        event: SubscriptionEvent, subscription_id: str | None, _conn: Any
    ) -> bool:
        cle = (event.provider_slug, event.provider_event_id)
        if cle in etat["vus"]:
            return False
        etat["vus"].add(cle)
        etat["journal"].append((event, subscription_id))
        return True

    async def _get(subscription_id: str, _conn: Any) -> Subscription | None:
        return etat["abonnements"].get(subscription_id)

    async def _par_fournisseur(identifiant: str, _conn: Any) -> Subscription | None:
        if not identifiant:
            return None
        return next(
            (s for s in etat["abonnements"].values() if s.provider_subscription_id == identifiant),
            None,
        )

    async def _enregistrer_etat(abonnement: Subscription, _conn: Any) -> None:
        etat["etats"].append(abonnement)

    for nom, impl in {
        "get_provider": _get_provider,
        "reveal_system_secret": _reveal,
        "enregistrer": _enregistrer,
        "get": _get,
        "par_identifiant_fournisseur": _par_fournisseur,
        "enregistrer_etat": _enregistrer_etat,
    }.items():
        monkeypatch.setattr(routes, nom, impl)

    client = TestClient(app)
    client.etat = etat  # type: ignore[attr-defined]
    return client


def _charge(type_: str = "invoice.paid", **objet: Any) -> bytes:
    base: dict[str, Any] = {"billing_reason": "subscription_create"}
    base.update(objet)
    return json.dumps(
        {
            "id": "evt_1",
            "type": type_,
            "data": {
                "object": {
                    **base,
                    "metadata": {"portal_subscription_id": ABO_ID},
                }
            },
        }
    ).encode()


def _poster(client: TestClient, corps: bytes, signature: str | None = None) -> Any:
    entetes = {"Stripe-Signature": signature if signature is not None else _signer(corps)}
    return client.post("/webhooks/paiement/stripe-fr", content=corps, headers=entetes)


# ─── Ce que la route refuse ──────────────────────────────────────────────────


def test_un_canal_inconnu_rend_404(client: TestClient) -> None:
    """Et ne dit rien de plus : un scan ne doit pas apprendre quels slugs existent."""
    corps = _charge()
    reponse = client.post(
        "/webhooks/paiement/fantome", content=corps, headers={"Stripe-Signature": _signer(corps)}
    )

    assert reponse.status_code == 404


def test_une_signature_absente_est_refusee(client: TestClient) -> None:
    assert _poster(client, _charge(), signature="").status_code == 400


def test_une_charge_modifiee_apres_signature_est_refusee(client: TestClient) -> None:
    """Le cœur du dispositif : la signature porte sur les octets reçus."""
    signature = _signer(_charge())

    assert _poster(client, _charge(amount_paid=999_999), signature).status_code == 400


def test_sans_secret_configure_rien_ne_passe(client: TestClient) -> None:
    """Un canal sans secret n'authentifie rien : l'ouvrir ouvrirait la route."""
    client.etat["secret"] = ""  # type: ignore[attr-defined]

    assert _poster(client, _charge()).status_code == 400


def test_rien_n_est_journalise_quand_la_signature_echoue(client: TestClient) -> None:
    """Une charge non authentifiée ne doit laisser aucune trace exploitable."""
    _poster(client, _charge(), signature="t=1,v1=faux")

    assert client.etat["journal"] == []  # type: ignore[attr-defined]


def test_une_charge_illisible_est_refusee(client: TestClient) -> None:
    corps = b"ceci n'est pas du json"

    assert _poster(client, corps).status_code == 400


# ─── Ce que la route applique ────────────────────────────────────────────────


def test_une_premiere_facture_payee_active_l_abonnement(client: TestClient) -> None:
    reponse = _poster(client, _charge())

    assert reponse.status_code == 200
    assert reponse.json()["statut"] == "applique"
    (maj,) = client.etat["etats"]  # type: ignore[attr-defined]
    assert maj.state == "actif"


def test_un_rejeu_ne_s_applique_pas_deux_fois(client: TestClient) -> None:
    """LE test de l'idempotence. Un fournisseur réémet, souvent en rafale."""
    _poster(client, _charge())
    reponse = _poster(client, _charge())

    assert reponse.status_code == 200
    assert reponse.json()["statut"] == "deja_traite"
    # Une seule transition appliquée, malgré deux réceptions.
    assert len(client.etat["etats"]) == 1  # type: ignore[attr-defined]


def test_un_evenement_qui_ne_nous_regarde_pas_repond_200(client: TestClient) -> None:
    """Ni erreur ni trace : le fournisseur émet quantité d'événements."""
    reponse = _poster(client, _charge(type_="customer.updated"))

    assert reponse.status_code == 200
    assert reponse.json()["statut"] == "ignore"
    assert client.etat["journal"] == []  # type: ignore[attr-defined]


def test_un_evenement_orphelin_est_trace_mais_accepte(client: TestClient) -> None:
    """Authentique, rattaché à rien de connu.

    On répond 200 : une erreur ferait réessayer indéfiniment, puis désactiver le
    point de terminaison — et l'on perdrait les événements suivants.
    """
    client.etat["abonnements"] = {}  # type: ignore[attr-defined]

    reponse = _poster(client, _charge())

    assert reponse.status_code == 200
    assert reponse.json()["statut"] == "orphelin"
    # Tracé quand même : c'est l'écart qu'on voudra relire.
    assert len(client.etat["journal"]) == 1  # type: ignore[attr-defined]


def test_l_abonnement_se_resout_par_l_identifiant_fournisseur(client: TestClient) -> None:
    """Repli quand la métadonnée est absente — un abonnement créé hors portail."""
    client.etat["abonnements"] = {  # type: ignore[attr-defined]
        "abo": _abonnement(
            id="22222222-2222-2222-2222-222222222222",
            provider_subscription_id="sub_ext",
        )
    }
    corps = json.dumps(
        {
            "id": "evt_2",
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_ext"}},
        }
    ).encode()

    reponse = _poster(client, corps)

    assert reponse.json()["statut"] == "applique"
    (maj,) = client.etat["etats"]  # type: ignore[attr-defined]
    assert maj.state == "resilie"


def test_une_transition_impossible_est_refusee_sans_erreur(client: TestClient) -> None:
    """Un renouvellement sur un abonnement résilié : réel, mais inapplicable.

    Il reste journalisé — c'est justement ce qu'on voudra relire.
    """
    client.etat["abonnements"][ABO_ID] = _abonnement(state="resilie")  # type: ignore[attr-defined]
    corps = json.dumps(
        {
            "id": "evt_3",
            "type": "invoice.paid",
            "data": {
                "object": {
                    "billing_reason": "subscription_cycle",
                    "metadata": {"portal_subscription_id": ABO_ID},
                }
            },
        }
    ).encode()

    reponse = _poster(client, corps)

    assert reponse.status_code == 200
    assert reponse.json()["statut"] == "refuse"
    assert client.etat["etats"] == []  # type: ignore[attr-defined]
    assert len(client.etat["journal"]) == 1  # type: ignore[attr-defined]
