"""Adaptateur Stripe : signature, traduction, et ouverture du paiement.

**Aucune dépendance au SDK Stripe.** La vérification de signature est un HMAC
SHA-256 sur `<horodatage>.<corps brut>`, et la traduction est une lecture de
JSON : embarquer une bibliothèque pour cela ajouterait une surface de mise à
jour sans rien apporter.

Le mapping suit ce que le cadrage a décidé, et il repose sur un champ que
Stripe ne met pas en évidence :

- **`billing_reason`** distingue, sur une facture payée, le PREMIER paiement
  (`subscription_create`) d'un renouvellement (`subscription_cycle`). Sans lui,
  les deux sont la même facture payée, et l'on enverrait un courriel de
  bienvenue à chaque échéance.

Le sens de SORTIE — ouvrir une session, couper la reconduction — repose sur deux
constats vérifiés contre l'API réelle, et non lus dans la documentation :

- le prix se décrit **en ligne** en mode abonnement, donc rien n'oblige à
  répliquer notre catalogue chez le fournisseur ;
- `cancel_at_period_end` est **refusé** à la création de session et ne s'accepte
  que sur l'abonnement. Un forfait sans tacite reconduction se reconduirait donc
  si l'on s'en tenait à l'ouverture.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import structlog

from ..canal import DemandePaiement, PaiementImpossible, SignatureInvalide
from ..subscriptions import EventKind, SubscriptionEvent

log = structlog.get_logger(__name__)

#: Racine de l'API. Constante nommée pour que les tests la détournent d'un seul
#: point plutôt que par des chaînes éparpillées.
API = "https://api.stripe.com"

#: Version d'API épinglée, telle que servie par le compte au moment du câblage.
#: La laisser implicite reviendrait à confier la forme de nos charges utiles à
#: un réglage de tableau de bord.
VERSION_API = "2026-08-26.dahlia"

#: Un paiement se joue devant un utilisateur qui attend. Au-delà, mieux vaut un
#: message d'échec qu'une page blanche.
DELAI = 15.0

#: Au-delà, une charge rejouée est refusée. Cinq minutes est la tolérance que
#: Stripe recommande : assez pour absorber une horloge décalée, trop court pour
#: qu'un enregistrement capté serve longtemps.
TOLERANCE = timedelta(minutes=5)


def _entetes_signature(valeur: str) -> tuple[int | None, list[str]]:
    """Décompose `t=...,v1=...,v1=...` en horodatage et signatures.

    PLUSIEURS `v1` peuvent coexister : c'est ce qui permet de renouveler un
    secret sans interruption. N'en accepter qu'une casserait la rotation.
    """
    horodatage: int | None = None
    signatures: list[str] = []
    for element in valeur.split(","):
        cle, _, val = element.strip().partition("=")
        if cle == "t":
            try:
                horodatage = int(val)
            except ValueError:
                return None, []
        elif cle == "v1":
            signatures.append(val)
    return horodatage, signatures


class CanalStripe:
    """Implémente `billing.canal.CanalDeVente` pour Stripe."""

    kind = "stripe"

    def verifier_signature(
        self,
        corps: bytes,
        en_tetes: Mapping[str, str],
        secret: str,
        maintenant: datetime,
    ) -> None:
        if not secret:
            # Sans secret configuré, on ne peut RIEN authentifier. Laisser
            # passer reviendrait à ouvrir la route à quiconque.
            raise SignatureInvalide("signature invalide")

        brut = next(
            (v for k, v in en_tetes.items() if k.lower() == "stripe-signature"),
            "",
        )
        horodatage, signatures = _entetes_signature(brut)
        if horodatage is None or not signatures:
            raise SignatureInvalide("signature invalide")

        # Fenêtre de rejeu. Le futur est borné aussi : une charge horodatée
        # dans dix minutes resterait valable dix minutes de trop.
        ecart = abs(maintenant.timestamp() - horodatage)
        if ecart > TOLERANCE.total_seconds():
            raise SignatureInvalide("signature invalide")

        attendue = hmac.new(
            secret.encode(),
            f"{horodatage}.".encode() + corps,
            hashlib.sha256,
        ).hexdigest()
        # `compare_digest` et non `==` : une comparaison qui s'arrête au premier
        # octet différent laisse mesurer où elle s'arrête.
        if not any(hmac.compare_digest(attendue, s) for s in signatures):
            raise SignatureInvalide("signature invalide")

    def normaliser(self, payload: Mapping[str, object]) -> SubscriptionEvent | None:
        # La charge snapshot est versionnée par l'endpoint : une version qui ne
        # correspond pas à celle épinglée signale une dérive de contrat côté
        # tableau de bord. Journalisée, pas refusée — refuser ferait rejouer le
        # fournisseur en boucle puis désactiver le point de terminaison.
        version = payload.get("api_version")
        if version and version != VERSION_API:
            log.warning(
                "webhook_version_api_inattendue",
                recue=str(version),
                epinglee=VERSION_API,
            )

        type_evenement = str(payload.get("type") or "")
        objet = cast(dict[str, Any], (payload.get("data") or {})).get("object") or {}
        if not isinstance(objet, dict):
            return None

        kind = self._kind(type_evenement, objet)
        if kind is None:
            return None

        identifiant = str(payload.get("id") or "")
        if not identifiant:
            # Sans identifiant, aucune idempotence : on préfère ignorer que
            # dédupliquer sur une clef vide partagée par tous les événements.
            return None

        return SubscriptionEvent(
            kind=kind,
            provider_slug="",  # posé par l'appelant : il sait QUELLE instance a signé.
            provider_event_id=identifiant,
            # Notre identifiant, s'il a été posé en métadonnée à la création de
            # la session. Sinon l'appelant résoudra par
            # `subscriptions.provider_subscription_id`.
            subscription_id=self._notre_identifiant(objet),
            payload=dict(payload),
            occurred_at=self._instant(payload),
        )

    # ─── Traduction ──────────────────────────────────────────────────────────

    @staticmethod
    def _kind(type_evenement: str, objet: Mapping[str, Any]) -> EventKind | None:
        if type_evenement == "customer.subscription.created":
            # Remonté QUEL QUE SOIT l'essai, et c'est délibéré. Sans `trial_end`
            # l'abonnement facture immédiatement, donc l'`activation` viendra de
            # la facture et non d'ici — mais l'événement doit tout de même
            # passer : c'est le SEUL endroit où le fournisseur nous rend
            # l'identifiant de l'abonnement qu'il vient de créer. L'ignorer
            # rendrait orpheline la facture qui suit.
            #
            # Sur l'ÉTAT c'est un non-événement : `debut_essai` laisse en
            # `essai`, où la souscription se trouve déjà.
            return "debut_essai"
        if type_evenement == "customer.subscription.deleted":
            return "resiliation"
        if type_evenement == "invoice.payment_failed":
            return "echec_paiement"
        if type_evenement == "invoice.paid":
            raison = objet.get("billing_reason")
            if raison == "subscription_create":
                return "activation"
            if raison == "subscription_cycle":
                return "renouvellement"
            # Facture hors cycle d'abonnement (ponctuelle, mise à jour de
            # moyen de paiement…) : elle ne fait pas avancer l'abonnement.
            return None
        # Survenus en exploitation réelle : total ou partiel pour le
        # remboursement (le montant vit dans le payload journalisé), fonds
        # gelés à l'ouverture d'un litige, issue won/lost à sa clôture. SANS
        # effet d'état tant que les arbitrages de la fiche « Remboursements et
        # litiges » ne sont pas tranchés — journalisés, jamais appliqués.
        if type_evenement == "charge.refunded":
            return "remboursement"
        if type_evenement == "charge.dispute.created":
            return "litige_ouvert"
        if type_evenement == "charge.dispute.closed":
            return "litige_clos"
        # Prélèvement hors session bloqué par une authentification forte requise :
        # le renouvellement à J+30 d'un abonnement dont la carte n'a pas été
        # authentifiée au setup. Journalisé, jamais ignoré en silence.
        if type_evenement == "invoice.payment_action_required":
            return "action_requise"
        return None

    @staticmethod
    def _notre_identifiant(objet: Mapping[str, Any]) -> str | None:
        metadonnees = objet.get("metadata")
        if not isinstance(metadonnees, dict):
            return None
        valeur = metadonnees.get("portal_subscription_id")
        return str(valeur) if valeur else None

    @staticmethod
    def identifiant_abonnement(payload: Mapping[str, object]) -> str | None:
        """Identifiant de l'abonnement CHEZ LE FOURNISSEUR, s'il est lisible.

        Il ne se lit pas au même endroit selon l'événement : sur une
        souscription c'est l'objet lui-même, sur une facture c'est le champ qui
        la rattache. Le confondre ferait enregistrer un identifiant de facture
        comme identifiant d'abonnement, et toute résolution ultérieure
        échouerait.
        """
        donnees = payload.get("data")
        objet = donnees.get("object") if isinstance(donnees, dict) else None
        if not isinstance(objet, dict):
            return None
        type_evenement = str(payload.get("type") or "")
        if type_evenement.startswith("customer.subscription."):
            brut = objet.get("id")
        else:
            # Basil (2025-03-31) a retiré `invoice.subscription` : le
            # rattachement vit sous `parent.subscription_details.subscription`,
            # gardé par `parent.type`. L'ancienne clef reste lue en repli —
            # elle ne coûte rien et couvre une charge rejouée d'avant Basil.
            brut = CanalStripe._abonnement_du_parent(objet) or objet.get("subscription")
        return str(brut) if brut else None

    @staticmethod
    def _abonnement_du_parent(objet: Mapping[str, Any]) -> str | None:
        parent = objet.get("parent")
        if not isinstance(parent, dict) or parent.get("type") != "subscription_details":
            return None
        details = parent.get("subscription_details")
        if not isinstance(details, dict):
            return None
        brut = details.get("subscription")
        return str(brut) if brut else None

    @staticmethod
    def _instant(payload: Mapping[str, object]) -> datetime | None:
        brut = payload.get("created")
        if not isinstance(brut, int):
            return None
        return datetime.fromtimestamp(brut, tz=UTC)

    # ─── Ouverture du paiement ───────────────────────────────────────────────

    async def ouvrir_paiement(self, demande: DemandePaiement, cle_api: str) -> str:
        """Crée une session de paiement hébergée et rend son URL.

        **Le prix est décrit EN LIGNE**, pas référencé par un identifiant Stripe.
        Vérifié contre l'API : `price_data` est accepté en mode abonnement. Le
        catalogue reste donc chez nous, seule source de vérité — synchroniser
        produits et prix chez le fournisseur ferait exister deux catalogues, et
        deux catalogues divergent.

        La durée passe en jours (`interval=day`), quelle qu'elle soit : c'est ce
        qui permet un forfait de 45 jours sans le tordre en « mois ».
        """
        corps: dict[str, str] = {
            "mode": "subscription",
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": demande.devise.lower(),
            "line_items[0][price_data][unit_amount]": str(demande.montant_minor),
            "line_items[0][price_data][product_data][name]": demande.libelle,
            "line_items[0][price_data][recurring][interval]": "day",
            "line_items[0][price_data][recurring][interval_count]": str(demande.duree_jours),
            "success_url": demande.url_succes,
            "cancel_url": demande.url_abandon,
            # Posée sur L'ABONNEMENT, pas sur la session : la session disparaît
            # du récit une fois payée, alors que les événements de cycle —
            # renouvellement, échec, résiliation — portent l'abonnement. Sur la
            # session seule, tout ce qui suit le premier paiement serait orphelin.
            "subscription_data[metadata][portal_subscription_id]": demande.subscription_id,
        }
        if demande.adresse is not None:
            # L'adresse figée part sur un CLIENT créé d'abord : la session de
            # paiement n'accepte pas d'adresse directement — c'est le client qui
            # la porte, et Checkout la reprend. Idempotent par abonnement : deux
            # clics ne créent pas deux clients.
            adr = demande.adresse
            corps_client = {
                "address[line1]": adr.line1,
                "address[city]": adr.city,
                "address[postal_code]": adr.postal_code,
                "address[country]": adr.country,
                "metadata[portal_subscription_id]": demande.subscription_id,
            }
            if adr.line2:
                corps_client["address[line2]"] = adr.line2
            if adr.state:
                corps_client["address[state]"] = adr.state
            if demande.email:
                corps_client["email"] = demande.email
            client_paiement = await self._appeler(
                "/v1/customers",
                corps_client,
                cle_api,
                idempotence=f"client:{demande.subscription_id}",
            )
            identifiant = client_paiement.get("id")
            if not isinstance(identifiant, str) or not identifiant:
                raise PaiementImpossible("le canal n'a pas rendu d'identifiant de client")
            # `customer` et `customer_email` sont exclusifs : l'email vit déjà
            # sur le client créé.
            corps["customer"] = identifiant
        elif demande.email:
            corps["customer_email"] = demande.email

        session = await self._appeler(
            "/v1/checkout/sessions",
            corps,
            cle_api,
            # Idempotence côté fournisseur : deux clics ne doivent pas ouvrir
            # deux sessions, donc facturer deux fois. Notre identifiant
            # d'abonnement est la clef naturelle — il est unique et stable.
            idempotence=f"paiement:{demande.subscription_id}",
        )
        url = session.get("url")
        if not isinstance(url, str) or not url:
            # Accepté mais sans URL : on ne rend pas de chaîne vide, l'appelant
            # redirigerait vers nulle part et le client croirait avoir payé.
            raise PaiementImpossible("le canal n'a pas rendu d'URL de paiement")
        return url

    async def couper_reconduction(self, provider_subscription_id: str, cle_api: str) -> None:
        """Programme l'arrêt au terme de la période en cours.

        `cancel_at_period_end` est REFUSÉ à la création de session — vérifié
        contre l'API. Il ne s'accepte que sur l'abonnement, donc après coup.
        C'est la raison d'être de cette seconde méthode : sans elle, un forfait
        déclaré sans tacite reconduction se reconduirait quand même.
        """
        await self._appeler(
            f"/v1/subscriptions/{provider_subscription_id}",
            {"cancel_at_period_end": "true"},
            cle_api,
            idempotence=f"sans-reconduction:{provider_subscription_id}",
        )

    @staticmethod
    async def _appeler(
        chemin: str, corps: Mapping[str, str], cle_api: str, idempotence: str
    ) -> dict[str, Any]:
        """Un appel à l'API du fournisseur, authentifié et versionné."""
        if not cle_api:
            # Sans clef, l'appel partirait pour revenir en 401. Autant le dire
            # ici, où la cause est lisible.
            raise PaiementImpossible("aucune clef d'API n'est configurée pour ce canal")

        async with httpx.AsyncClient(timeout=DELAI) as client:
            try:
                reponse = await client.post(
                    f"{API}{chemin}",
                    data=dict(corps),
                    auth=(cle_api, ""),
                    headers={
                        # Version ÉPINGLÉE : sans elle, un changement fait au
                        # tableau de bord modifierait la forme des réponses et
                        # des webhooks sans qu'on touche une ligne de code.
                        "Stripe-Version": VERSION_API,
                        "Idempotency-Key": idempotence,
                    },
                )
            except httpx.HTTPError as exc:
                raise PaiementImpossible("le canal de paiement est injoignable") from exc

        try:
            charge = reponse.json()
        except ValueError as exc:
            raise PaiementImpossible("réponse illisible du canal de paiement") from exc
        if not isinstance(charge, dict):
            raise PaiementImpossible("réponse illisible du canal de paiement")

        if reponse.status_code >= 400:
            erreur = charge.get("error")
            motif = erreur.get("message") if isinstance(erreur, dict) else None
            # Le motif du fournisseur est journalisé par l'appelant, pas rendu
            # tel quel à l'utilisateur : il décrit notre requête, pas son
            # problème à lui.
            raise PaiementImpossible(str(motif or f"refus du canal ({reponse.status_code})"))
        return cast(dict[str, Any], charge)
