"""Émission des événements de cycle d'abonnement vers le bus applicatif.

Le canal de vente parle en `kind` (`debut_essai`, `activation`, …) ; le bus — et
derrière lui les automates du workflow — parle en types du registre fermé
(`subscription.trial_started`, …). Ce module porte la table de correspondance et
la construction du payload, à UN seul endroit : le webhook, la souscription
gratuite et l'octroi d'essai émettent tous la même chose.

Le contenu du payload est celui DÉCIDÉ par la fiche « Automate — événements
user (forfait) » : références métier (`user_id`, `user_email`, `offre_slug`,
`subscription_id` — la clé d'idempotence des règles d'automate) et variables
personnalisées de l'offre. Les métadonnées système (`_eventId`, `_timestamp`,
`_source`) sont posées par l'enveloppe du producteur, pas ici.

L'émission est **best-effort et hors transaction** : un abonnement appliqué
sans événement émis se rattrape (backfill, rejeu) ; une transition annulée
parce que le bus a toussé serait un mensonge envers le fournisseur de paiement,
qui a déjà acté l'événement de son côté.
"""

from __future__ import annotations

from typing import Any

import structlog

from .subscriptions import EventKind, Subscription

log = structlog.get_logger(__name__)

#: kind du canal de vente → type du registre d'événements applicatifs.
#: Table EXHAUSTIVE sur EventKind : ajouter un kind sans décider de son
#: événement est une erreur détectée par les tests, pas un silence.
TYPE_PAR_KIND: dict[EventKind, str] = {
    "debut_essai": "subscription.trial_started",
    "activation": "subscription.activated",
    "renouvellement": "subscription.renewed",
    "echec_paiement": "subscription.payment_failed",
    "resiliation": "subscription.cancelled",
    # Informatifs : journalisés sans transition (arbitrages produit ouverts).
    "remboursement": "subscription.refunded",
    "litige_ouvert": "subscription.dispute_opened",
    "litige_clos": "subscription.dispute_closed",
    "action_requise": "subscription.payment_action_required",
}

TYPE_RETENTION_EXPIREE = "subscription.retention_expired"


async def publier_evenement_abonnement(
    kind: EventKind,
    abonnement: Subscription,
    *,
    provider_event_id: str,
    conn: Any,
    type_evenement: str | None = None,
    complement: dict[str, Any] | None = None,
) -> None:
    """Émet l'événement applicatif d'une transition d'abonnement.

    `provider_event_id` sert de `dedup_key` : les automates dédupliquent sur la
    même clé que le journal des webhooks — un rejeu de webhook déjà écarté par
    l'idempotence n'arrive pas ici, mais la clé protège aussi les chemins
    internes (souscription gratuite, octroi d'essai).

    `type_evenement` permet au scheduler de rétention d'émettre son propre type
    (`subscription.retention_expired`) avec le même payload de base ;
    `complement` y ajoute ses champs propres (délai appliqué, état).

    Ne lève jamais : l'échec est journalisé en erreur — la transition est déjà
    actée, l'événement se rattrape, un rollback ne se rattraperait pas.
    """
    from ..db.billing_offers import get_offer
    from ..db.user_config import email_de
    from ..events.bus import emit_event

    try:
        offre = await get_offer(abonnement.offer_slug, conn)
        email = await email_de(abonnement.login, conn)
        subject: dict[str, Any] = {
            "user_id": abonnement.login,
            "user_email": email,
            "offre_slug": abonnement.offer_slug,
            "subscription_id": abonnement.id,
            "hosting_type": offre.hosting_type if offre else "",
            "state": abonnement.state,
            "variables": dict(offre.variables) if offre else {},
        }
        if complement:
            subject.update(complement)
        await emit_event(
            type_evenement or TYPE_PAR_KIND[kind],
            actor=abonnement.login,
            subject=subject,
            dedup_key=provider_event_id,
        )
    except Exception:  # noqa: BLE001 — l'événement se rattrape, pas la transition
        log.error(
            "evenement_abonnement_non_emis",
            kind=kind,
            subscription_id=abonnement.id,
            exc_info=True,
        )

    # L'email du cycle suit le même fait générateur, depuis le même entonnoir :
    # webhook, souscription gratuite, octroi d'essai et clôture au terme passent
    # tous ici. Le type rétention émet le sien via le balayeur d'avertissements,
    # pas ici. Best-effort : envoyer_email_cycle ne lève jamais.
    if type_evenement is None:
        from ..emails.service import KINDS_AVEC_EMAIL, envoyer_email_cycle

        if kind in KINDS_AVEC_EMAIL:
            await envoyer_email_cycle(
                kind, abonnement, provider_event_id=provider_event_id, conn=conn
            )
