"""Ouverture d'une session de paiement, et coupure de la reconduction.

Ces tests portent sur la REQUÊTE que l'adaptateur émet, autant que sur ce qu'il
fait de la réponse. C'est délibéré : les paramètres vérifiés ici l'ont d'abord
été contre l'API réelle, et un test qui n'inspecterait que la valeur de retour
laisserait passer une requête devenue fausse.

Ce qu'ils NE prouvent pas : qu'un vrai paiement aboutisse. Un double répond ce
qu'on lui a dit de répondre. Tant qu'un compte réel n'a pas encaissé, rien ici
ne vaut validation.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from portal.billing.canal import DemandePaiement, PaiementImpossible
from portal.billing.canaux.stripe import API, VERSION_API, CanalStripe

CLE = "sk_test_doublure"


def _demande(**extra: Any) -> DemandePaiement:
    base: dict[str, Any] = {
        "subscription_id": "11111111-1111-1111-1111-111111111111",
        "libelle": "Standard",
        "devise": "EUR",
        "montant_minor": 1200,
        "duree_jours": 30,
        "reconduction": True,
        "email": "alice@example.org",
        "url_succes": "https://portail/retour",
        "url_abandon": "https://portail/forfaits",
    }
    base.update(extra)
    return DemandePaiement(**base)


def _envoye(route: Any) -> dict[str, str]:
    """Corps de la dernière requête, décodé en dictionnaire plat."""
    brut = route.calls.last.request.content.decode()
    return {k: v[0] for k, v in parse_qs(brut).items()}


# ─── Ouverture ───────────────────────────────────────────────────────────────


@respx.mock
@pytest.mark.asyncio
async def test_l_url_de_paiement_est_rendue() -> None:
    respx.post(f"{API}/v1/checkout/sessions").mock(
        return_value=httpx.Response(200, json={"id": "cs_1", "url": "https://paiement/cs_1"})
    )

    url = await CanalStripe().ouvrir_paiement(_demande(), CLE)

    assert url == "https://paiement/cs_1"


@respx.mock
@pytest.mark.asyncio
async def test_le_prix_part_en_ligne_sans_identifiant_de_catalogue() -> None:
    """Le catalogue reste chez nous : rien n'est répliqué chez le fournisseur."""
    route = respx.post(f"{API}/v1/checkout/sessions").mock(
        return_value=httpx.Response(200, json={"url": "https://paiement/cs_1"})
    )

    await CanalStripe().ouvrir_paiement(_demande(), CLE)

    corps = _envoye(route)
    assert corps["line_items[0][price_data][unit_amount]"] == "1200"
    assert corps["line_items[0][price_data][currency]"] == "eur"
    assert corps["mode"] == "subscription"
    # Aucun identifiant de prix : c'est tout l'intérêt.
    assert "line_items[0][price]" not in corps


@respx.mock
@pytest.mark.asyncio
async def test_une_duree_arbitraire_part_en_jours() -> None:
    """45 jours est un forfait valide — le tordre en « mois » le fausserait."""
    route = respx.post(f"{API}/v1/checkout/sessions").mock(
        return_value=httpx.Response(200, json={"url": "https://paiement/cs_1"})
    )

    await CanalStripe().ouvrir_paiement(_demande(duree_jours=45), CLE)

    corps = _envoye(route)
    assert corps["line_items[0][price_data][recurring][interval]"] == "day"
    assert corps["line_items[0][price_data][recurring][interval_count]"] == "45"


@respx.mock
@pytest.mark.asyncio
async def test_notre_identifiant_est_pose_sur_l_abonnement_pas_sur_la_session() -> None:
    """LE point qui rend le webhook capable de rattacher les événements.

    Sur la session seule, tout ce qui suit le premier paiement — renouvellement,
    échec, résiliation — arriverait orphelin.
    """
    route = respx.post(f"{API}/v1/checkout/sessions").mock(
        return_value=httpx.Response(200, json={"url": "https://paiement/cs_1"})
    )

    await CanalStripe().ouvrir_paiement(_demande(), CLE)

    corps = _envoye(route)
    assert corps["subscription_data[metadata][portal_subscription_id]"] == (
        "11111111-1111-1111-1111-111111111111"
    )


@respx.mock
@pytest.mark.asyncio
async def test_deux_clics_portent_la_meme_clef_d_idempotence() -> None:
    """Sans elle, un double clic ouvre deux sessions donc facture deux fois."""
    route = respx.post(f"{API}/v1/checkout/sessions").mock(
        return_value=httpx.Response(200, json={"url": "https://paiement/cs_1"})
    )
    canal = CanalStripe()

    await canal.ouvrir_paiement(_demande(), CLE)
    premiere = route.calls.last.request.headers["Idempotency-Key"]
    await canal.ouvrir_paiement(_demande(), CLE)

    assert route.calls.last.request.headers["Idempotency-Key"] == premiere


@respx.mock
@pytest.mark.asyncio
async def test_la_version_d_api_est_epinglee() -> None:
    """Sans épinglage, un réglage de tableau de bord change nos charges utiles."""
    route = respx.post(f"{API}/v1/checkout/sessions").mock(
        return_value=httpx.Response(200, json={"url": "https://paiement/cs_1"})
    )

    await CanalStripe().ouvrir_paiement(_demande(), CLE)

    assert route.calls.last.request.headers["Stripe-Version"] == VERSION_API


@respx.mock
@pytest.mark.asyncio
async def test_sans_email_connu_le_champ_est_absent() -> None:
    """Un email vide pré-remplirait la page de paiement avec du vide."""
    route = respx.post(f"{API}/v1/checkout/sessions").mock(
        return_value=httpx.Response(200, json={"url": "https://paiement/cs_1"})
    )

    await CanalStripe().ouvrir_paiement(_demande(email=""), CLE)

    assert "customer_email" not in _envoye(route)


# ─── Ce qui échoue ───────────────────────────────────────────────────────────


@respx.mock
@pytest.mark.asyncio
async def test_un_refus_du_fournisseur_leve_paiement_impossible() -> None:
    respx.post(f"{API}/v1/checkout/sessions").mock(
        return_value=httpx.Response(400, json={"error": {"message": "montant invalide"}})
    )

    with pytest.raises(PaiementImpossible, match="montant invalide"):
        await CanalStripe().ouvrir_paiement(_demande(), CLE)


@respx.mock
@pytest.mark.asyncio
async def test_une_reponse_sans_url_ne_rend_pas_une_chaine_vide() -> None:
    """Sinon l'appelant redirige vers nulle part et le client se croit engagé."""
    respx.post(f"{API}/v1/checkout/sessions").mock(
        return_value=httpx.Response(200, json={"id": "cs_1"})
    )

    with pytest.raises(PaiementImpossible):
        await CanalStripe().ouvrir_paiement(_demande(), CLE)


@respx.mock
@pytest.mark.asyncio
async def test_un_canal_injoignable_leve_paiement_impossible() -> None:
    respx.post(f"{API}/v1/checkout/sessions").mock(side_effect=httpx.ConnectError("nope"))

    with pytest.raises(PaiementImpossible, match="injoignable"):
        await CanalStripe().ouvrir_paiement(_demande(), CLE)


@pytest.mark.asyncio
async def test_sans_clef_aucun_appel_n_est_emis() -> None:
    """L'appel partirait pour revenir en 401 : autant le dire où c'est lisible."""
    with respx.mock:
        route = respx.post(f"{API}/v1/checkout/sessions")

        with pytest.raises(PaiementImpossible, match="clef"):
            await CanalStripe().ouvrir_paiement(_demande(), "")

        assert not route.called


# ─── Coupure de la reconduction ──────────────────────────────────────────────


@respx.mock
@pytest.mark.asyncio
async def test_la_coupure_se_pose_sur_l_abonnement() -> None:
    """Refusé à l'ouverture de session — vérifié contre l'API réelle."""
    route = respx.post(f"{API}/v1/subscriptions/sub_1").mock(
        return_value=httpx.Response(200, json={"id": "sub_1", "cancel_at_period_end": True})
    )

    await CanalStripe().couper_reconduction("sub_1", CLE)

    assert _envoye(route)["cancel_at_period_end"] == "true"


@respx.mock
@pytest.mark.asyncio
async def test_une_coupure_refusee_remonte() -> None:
    """Silencieuse, elle laisserait se reconduire un forfait qui ne le doit pas."""
    respx.post(f"{API}/v1/subscriptions/sub_1").mock(
        return_value=httpx.Response(404, json={"error": {"message": "No such subscription"}})
    )

    with pytest.raises(PaiementImpossible, match="No such subscription"):
        await CanalStripe().couper_reconduction("sub_1", CLE)


# ─── L'adresse de facturation transmise au canal ─────────────────────────────


def _adresse(**extra: Any) -> Any:
    from portal.billing.adresse import AdresseFacturation

    base: dict[str, Any] = {
        "line1": "12 rue des Lilas",
        "city": "Lyon",
        "postal_code": "69003",
        "country": "FR",
    }
    base.update(extra)
    return AdresseFacturation.model_validate(base)


@respx.mock
@pytest.mark.asyncio
async def test_l_adresse_part_structuree_sur_un_client_cree_d_abord() -> None:
    """La session n'accepte pas d'adresse directement : elle vit sur le CLIENT,
    créé avant la session — idempotent par abonnement — et Checkout la reprend."""
    route_client = respx.post(f"{API}/v1/customers").mock(
        return_value=httpx.Response(200, json={"id": "cus_42"})
    )
    route_session = respx.post(f"{API}/v1/checkout/sessions").mock(
        return_value=httpx.Response(200, json={"url": "https://paiement/cs_1"})
    )

    await CanalStripe().ouvrir_paiement(_demande(adresse=_adresse()), CLE)

    corps_client = _envoye(route_client)
    assert corps_client["address[line1]"] == "12 rue des Lilas"
    assert corps_client["address[city]"] == "Lyon"
    assert corps_client["address[postal_code]"] == "69003"
    assert corps_client["address[country]"] == "FR"
    assert corps_client["email"] == "alice@example.org"
    # Champs vides ABSENTS, pas envoyés à blanc.
    assert "address[line2]" not in corps_client
    assert "address[state]" not in corps_client

    corps_session = _envoye(route_session)
    assert corps_session["customer"] == "cus_42"
    # `customer` et `customer_email` sont exclusifs : l'email vit sur le client.
    assert "customer_email" not in corps_session


@respx.mock
@pytest.mark.asyncio
async def test_sans_adresse_aucun_client_n_est_cree() -> None:
    route_client = respx.post(f"{API}/v1/customers").mock(
        return_value=httpx.Response(200, json={"id": "cus_42"})
    )
    route_session = respx.post(f"{API}/v1/checkout/sessions").mock(
        return_value=httpx.Response(200, json={"url": "https://paiement/cs_1"})
    )

    await CanalStripe().ouvrir_paiement(_demande(), CLE)

    assert not route_client.called
    assert _envoye(route_session)["customer_email"] == "alice@example.org"


@respx.mock
@pytest.mark.asyncio
async def test_un_client_sans_identifiant_est_un_echec_franc() -> None:
    respx.post(f"{API}/v1/customers").mock(return_value=httpx.Response(200, json={}))

    with pytest.raises(PaiementImpossible):
        await CanalStripe().ouvrir_paiement(_demande(adresse=_adresse()), CLE)
