"""Adaptateur Stripe : signature, puis traduction vers les cinq événements.

**Aucune dépendance au SDK Stripe.** La vérification de signature est un HMAC
SHA-256 sur `<horodatage>.<corps brut>`, et la traduction est une lecture de
JSON : embarquer une bibliothèque pour cela ajouterait une surface de mise à
jour sans rien apporter.

Le mapping suit ce que le cadrage a décidé, et il repose sur deux champs que
Stripe ne met pas en évidence :

- **`trial_end`** distingue une souscription qui ouvre un essai d'une
  souscription qui facture tout de suite ;
- **`billing_reason`** distingue, sur une facture payée, le PREMIER paiement
  (`subscription_create`) d'un renouvellement (`subscription_cycle`). Sans lui,
  les deux sont la même facture payée, et l'on enverrait un courriel de
  bienvenue à chaque échéance.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from ..canal import SignatureInvalide
from ..subscriptions import EventKind, SubscriptionEvent

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
            # Sans `trial_end`, la souscription facture immédiatement :
            # l'`activation` viendra de la facture, pas d'ici.
            return "debut_essai" if objet.get("trial_end") else None
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
        return None

    @staticmethod
    def _notre_identifiant(objet: Mapping[str, Any]) -> str | None:
        metadonnees = objet.get("metadata")
        if not isinstance(metadonnees, dict):
            return None
        valeur = metadonnees.get("portal_subscription_id")
        return str(valeur) if valeur else None

    @staticmethod
    def _instant(payload: Mapping[str, object]) -> datetime | None:
        brut = payload.get("created")
        if not isinstance(brut, int):
            return None
        return datetime.fromtimestamp(brut, tz=UTC)
