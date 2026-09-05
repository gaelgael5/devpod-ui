"""Adaptateur Stripe : ce qu'on authentifie, et ce qu'on traduit.

Ces tests sont la seule chose qui tienne lieu de vérification tant qu'aucun
compte de paiement n'existe. Ils prouvent que le mapping est celui qui a été
décidé et que la signature est réellement vérifiée.

Ils ne prouvent PAS qu'un paiement fonctionne : les charges utiles sont écrites
ici, pas reçues de Stripe. Le jour où un compte réel émettra un webhook, c'est
la forme des charges qui pourra surprendre — format abrégé, champ optionnel
absent — et aucun test de ce fichier ne l'aura vu venir.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from portal.billing.canal import SignatureInvalide
from portal.billing.canaux.stripe import CanalStripe

SECRET = "whsec_de_test_pas_un_vrai"
MAINTENANT = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _signer(corps: bytes, secret: str = SECRET, instant: datetime = MAINTENANT) -> str:
    horodatage = int(instant.timestamp())
    signature = hmac.new(
        secret.encode(), f"{horodatage}.".encode() + corps, hashlib.sha256
    ).hexdigest()
    return f"t={horodatage},v1={signature}"


def _corps(**payload: Any) -> bytes:
    return json.dumps(payload).encode()


@pytest.fixture
def canal() -> CanalStripe:
    return CanalStripe()


# ─── Signature ───────────────────────────────────────────────────────────────


def test_une_signature_valide_passe(canal: CanalStripe) -> None:
    corps = _corps(id="evt_1", type="invoice.paid")

    canal.verifier_signature(corps, {"Stripe-Signature": _signer(corps)}, SECRET, MAINTENANT)


def test_l_en_tete_est_insensible_a_la_casse(canal: CanalStripe) -> None:
    """Les serveurs normalisent la casse différemment ; on ne s'y fie pas."""
    corps = _corps(id="evt_1")

    canal.verifier_signature(corps, {"stripe-signature": _signer(corps)}, SECRET, MAINTENANT)


def test_un_corps_modifie_est_refuse(canal: CanalStripe) -> None:
    """Le cœur du dispositif : la signature porte sur le corps EXACT."""
    signature = _signer(_corps(id="evt_1", amount=100))

    with pytest.raises(SignatureInvalide):
        canal.verifier_signature(
            _corps(id="evt_1", amount=999_999),
            {"Stripe-Signature": signature},
            SECRET,
            MAINTENANT,
        )


def test_un_corps_reserialise_est_refuse(canal: CanalStripe) -> None:
    """Le piège d'exploitation : un proxy qui reformate le JSON casse tout.

    Le symptôme — « signature invalide » sur des webhooks parfaitement valides —
    est pénible à rapporter à sa cause. Ce test le documente.
    """
    original = b'{"id":"evt_1","type":"invoice.paid"}'
    signature = _signer(original)
    reformate = json.dumps(json.loads(original), indent=2).encode()

    with pytest.raises(SignatureInvalide):
        canal.verifier_signature(reformate, {"Stripe-Signature": signature}, SECRET, MAINTENANT)


def test_un_mauvais_secret_est_refuse(canal: CanalStripe) -> None:
    corps = _corps(id="evt_1")
    signature = _signer(corps, secret="whsec_autre")

    with pytest.raises(SignatureInvalide):
        canal.verifier_signature(corps, {"Stripe-Signature": signature}, SECRET, MAINTENANT)


def test_sans_secret_configure_rien_ne_passe(canal: CanalStripe) -> None:
    """Sans secret, on n'authentifie RIEN : laisser passer ouvrirait la route."""
    corps = _corps(id="evt_1")

    with pytest.raises(SignatureInvalide):
        canal.verifier_signature(corps, {"Stripe-Signature": _signer(corps)}, "", MAINTENANT)


def test_une_charge_trop_ancienne_est_refusee(canal: CanalStripe) -> None:
    """Protection contre le rejeu : une charge captée ne sert pas longtemps."""
    vieux = MAINTENANT - timedelta(minutes=10)
    corps = _corps(id="evt_1")

    with pytest.raises(SignatureInvalide):
        canal.verifier_signature(
            corps, {"Stripe-Signature": _signer(corps, instant=vieux)}, SECRET, MAINTENANT
        )


def test_une_charge_horodatee_dans_le_futur_est_refusee(canal: CanalStripe) -> None:
    """Le futur est borné aussi : sinon la charge resterait valable trop longtemps."""
    futur = MAINTENANT + timedelta(minutes=10)
    corps = _corps(id="evt_1")

    with pytest.raises(SignatureInvalide):
        canal.verifier_signature(
            corps, {"Stripe-Signature": _signer(corps, instant=futur)}, SECRET, MAINTENANT
        )


def test_plusieurs_signatures_permettent_la_rotation(canal: CanalStripe) -> None:
    """Stripe envoie plusieurs `v1` pendant un renouvellement de secret.

    N'en accepter qu'une casserait la rotation, et l'on ne s'en apercevrait
    qu'au moment de changer le secret — c'est-à-dire au pire moment.
    """
    corps = _corps(id="evt_1")
    bonne = _signer(corps).split("v1=")[1]
    horodatage = int(MAINTENANT.timestamp())

    canal.verifier_signature(
        corps,
        {"Stripe-Signature": f"t={horodatage},v1=deadbeef,v1={bonne}"},
        SECRET,
        MAINTENANT,
    )


def test_un_en_tete_absent_ou_illisible_est_refuse(canal: CanalStripe) -> None:
    corps = _corps(id="evt_1")

    for entetes in (
        {},
        {"Stripe-Signature": ""},
        {"Stripe-Signature": "n'importe quoi"},
        {"Stripe-Signature": "t=abc,v1=def"},
    ):
        with pytest.raises(SignatureInvalide):
            canal.verifier_signature(corps, entetes, SECRET, MAINTENANT)


# ─── Traduction vers les cinq événements ─────────────────────────────────────


def _evenement(type_: str, objet: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"id": "evt_1", "type": type_, "data": {"object": objet}, **extra}


def test_une_souscription_avec_essai_ouvre_un_debut_d_essai(canal: CanalStripe) -> None:
    charge = _evenement("customer.subscription.created", {"trial_end": 1_800_000_000})

    evenement = canal.normaliser(charge)

    assert evenement is not None
    assert evenement.kind == "debut_essai"


def test_une_souscription_sans_essai_remonte_quand_meme(canal: CanalStripe) -> None:
    """Elle facture tout de suite, mais l'événement ne doit PAS être ignoré.

    C'est le seul endroit où le fournisseur rend l'identifiant de l'abonnement
    qu'il vient de créer. L'ignorer — ce que faisait la version précédente —
    rendait orpheline la facture qui suivait, faute de savoir à quoi la
    rattacher. Sur l'état, c'est un non-événement : on est déjà en `essai`.
    """
    charge = _evenement("customer.subscription.created", {"trial_end": None})

    evenement = canal.normaliser(charge)

    assert evenement is not None
    assert evenement.kind == "debut_essai"


def test_l_identifiant_d_abonnement_se_lit_sur_la_souscription(canal: CanalStripe) -> None:
    charge = _evenement("customer.subscription.created", {"id": "sub_42"})

    assert canal.identifiant_abonnement(charge) == "sub_42"


def test_l_identifiant_d_abonnement_se_lit_autrement_sur_une_facture(
    canal: CanalStripe,
) -> None:
    """Sur une facture, `id` est celui de la FACTURE — le confondre casserait tout."""
    charge = _evenement("invoice.paid", {"id": "in_7", "subscription": "sub_42"})

    assert canal.identifiant_abonnement(charge) == "sub_42"


def test_sans_rattachement_lisible_l_identifiant_est_absent(canal: CanalStripe) -> None:
    charge = _evenement("invoice.paid", {"id": "in_7"})

    assert canal.identifiant_abonnement(charge) is None


def test_un_remboursement_est_normalise(canal: CanalStripe) -> None:
    """Total ou partiel : le montant vit dans le payload, journalisé tel quel."""
    charge = _evenement(
        "charge.refunded", {"id": "ch_1", "amount_refunded": 600, "refunded": False}
    )

    evenement = canal.normaliser(charge)

    assert evenement is not None
    assert evenement.kind == "remboursement"
    assert evenement.payload["data"]["object"]["amount_refunded"] == 600


def test_un_litige_ouvert_et_sa_cloture_sont_normalises(canal: CanalStripe) -> None:
    ouvert = canal.normaliser(_evenement("charge.dispute.created", {"id": "dp_1"}))
    clos = canal.normaliser(_evenement("charge.dispute.closed", {"id": "dp_1", "status": "lost"}))

    assert ouvert is not None and ouvert.kind == "litige_ouvert"
    assert clos is not None and clos.kind == "litige_clos"
    assert clos.payload["data"]["object"]["status"] == "lost"


def test_une_authentification_requise_est_normalisee(canal: CanalStripe) -> None:
    """Le renouvellement hors session bloqué par 3DS : journalisé, jamais
    ignoré en silence (fiche SetupIntent)."""
    evt = canal.normaliser(_evenement("invoice.payment_action_required", {"id": "in_9"}))

    assert evt is not None
    assert evt.kind == "action_requise"


def test_la_premiere_facture_payee_active(canal: CanalStripe) -> None:
    charge = _evenement("invoice.paid", {"billing_reason": "subscription_create"})

    evenement = canal.normaliser(charge)

    assert evenement is not None
    assert evenement.kind == "activation"


def test_une_facture_de_cycle_renouvelle(canal: CanalStripe) -> None:
    """`billing_reason` est le SEUL champ qui distingue les deux.

    Sans lui, on enverrait un courriel de bienvenue à chaque échéance.
    """
    charge = _evenement("invoice.paid", {"billing_reason": "subscription_cycle"})

    evenement = canal.normaliser(charge)

    assert evenement is not None
    assert evenement.kind == "renouvellement"


def test_une_facture_hors_cycle_ne_fait_rien_avancer(canal: CanalStripe) -> None:
    charge = _evenement("invoice.paid", {"billing_reason": "manual"})

    assert canal.normaliser(charge) is None


def test_un_paiement_echoue_remonte_tel_quel(canal: CanalStripe) -> None:
    evenement = canal.normaliser(_evenement("invoice.payment_failed", {}))

    assert evenement is not None
    assert evenement.kind == "echec_paiement"


def test_une_souscription_supprimee_resilie(canal: CanalStripe) -> None:
    evenement = canal.normaliser(_evenement("customer.subscription.deleted", {}))

    assert evenement is not None
    assert evenement.kind == "resiliation"


def test_un_evenement_qui_ne_nous_regarde_pas_est_ignore(canal: CanalStripe) -> None:
    """`None` et non une exception : Stripe émet quantité d'événements.

    Les traiter comme des erreurs remplirait les journaux de bruit et masquerait
    les vrais échecs.
    """
    assert canal.normaliser(_evenement("customer.updated", {})) is None
    assert canal.normaliser(_evenement("payment_intent.succeeded", {})) is None


# ─── Ce qui rend l'événement exploitable ─────────────────────────────────────


def test_l_identifiant_de_l_evenement_est_conserve(canal: CanalStripe) -> None:
    """C'est la clef d'idempotence : sans elle, un rejeu s'applique deux fois."""
    charge = _evenement("customer.subscription.deleted", {})
    charge["id"] = "evt_特別"

    evenement = canal.normaliser(charge)

    assert evenement is not None
    assert evenement.provider_event_id == "evt_特別"


def test_un_evenement_sans_identifiant_est_ignore(canal: CanalStripe) -> None:
    """Plutôt qu'une déduplication sur une clef vide, partagée par tous."""
    charge = _evenement("customer.subscription.deleted", {})
    charge["id"] = ""

    assert canal.normaliser(charge) is None


def test_notre_identifiant_est_relu_des_metadonnees(canal: CanalStripe) -> None:
    """Posé à la création de la session, il évite une résolution indirecte."""
    charge = _evenement(
        "invoice.paid",
        {
            "billing_reason": "subscription_create",
            "metadata": {"portal_subscription_id": "abo-42"},
        },
    )

    evenement = canal.normaliser(charge)

    assert evenement is not None
    assert evenement.subscription_id == "abo-42"


def test_sans_metadonnee_l_appelant_devra_resoudre(canal: CanalStripe) -> None:
    charge = _evenement("invoice.paid", {"billing_reason": "subscription_create"})

    evenement = canal.normaliser(charge)

    assert evenement is not None
    assert evenement.subscription_id is None


def test_la_charge_brute_est_conservee(canal: CanalStripe) -> None:
    """On garde de quoi rejouer et de quoi expliquer, six mois plus tard."""
    charge = _evenement("customer.subscription.deleted", {"id": "sub_123"})

    evenement = canal.normaliser(charge)

    assert evenement is not None
    assert evenement.payload["type"] == "customer.subscription.deleted"


# ─── Contrat Basil+ : rattachement d'une facture, version d'API ──────────────


def test_l_identifiant_d_une_facture_se_lit_sous_parent_depuis_basil(
    canal: CanalStripe,
) -> None:
    """Basil (2025-03-31) a retiré `invoice.subscription` : le rattachement vit
    désormais sous `parent.subscription_details.subscription`. Avec la version
    épinglée (dahlia), c'est la SEULE forme que le fournisseur émet."""
    charge = _evenement(
        "invoice.paid",
        {
            "id": "in_7",
            "parent": {
                "type": "subscription_details",
                "subscription_details": {"subscription": "sub_42"},
            },
        },
    )

    assert canal.identifiant_abonnement(charge) == "sub_42"


def test_un_parent_d_un_autre_type_ne_rattache_pas(canal: CanalStripe) -> None:
    """`parent.type` doit valoir `subscription_details` — une facture de devis
    porte un parent d'un autre type, et n'a pas d'abonnement à rattacher."""
    charge = _evenement(
        "invoice.paid",
        {"id": "in_7", "parent": {"type": "quote_details", "quote_details": {}}},
    )

    assert canal.identifiant_abonnement(charge) is None


def test_une_version_api_inattendue_est_journalisee(canal: CanalStripe) -> None:
    """La charge snapshot est versionnée par l'endpoint : une version différente
    de celle épinglée signale une dérive de contrat — à voir, pas à refuser
    (refuser ferait rejouer le fournisseur en boucle)."""
    import structlog.testing

    charge = _evenement(
        "invoice.paid",
        {"billing_reason": "subscription_create"},
        api_version="2019-01-01",
    )

    with structlog.testing.capture_logs() as journaux:
        assert canal.normaliser(charge) is not None

    assert any(j["event"] == "webhook_version_api_inattendue" for j in journaux)


def test_la_version_epinglee_ne_journalise_rien(canal: CanalStripe) -> None:
    import structlog.testing

    from portal.billing.canaux.stripe import VERSION_API

    charge = _evenement(
        "invoice.paid",
        {"billing_reason": "subscription_create"},
        api_version=VERSION_API,
    )

    with structlog.testing.capture_logs() as journaux:
        assert canal.normaliser(charge) is not None

    assert not any(j["event"] == "webhook_version_api_inattendue" for j in journaux)
