"""La clôture des forfaits à leur terme : « s'arrêtera à son échéance », tenu.

Tout forfait est borné (`ends_at`, posé à la souscription), et le dépôt promet
depuis le début qu'une offre gratuite « ne recevra jamais d'activation et
s'arrêtera à son échéance ». Ce module est l'acteur de cette promesse : sans
lui, un essai expiré resterait servi indéfiniment.

Ce qu'il fait, abonnement par abonnement arrivé à terme :

- **jamais touche une offre à reconduction tacite** — son forfait repart, le
  terme se renouvelle côté canal de paiement, pas ici ;
- applique une résiliation SYNTHÉTIQUE (`terme:<id>:<échéance>`), journalisée
  dans `subscription_events` comme n'importe quel événement — c'est le journal
  qui porte l'idempotence, deux passes ne résilient qu'une fois ;
- émet `subscription.cancelled` : les automates arrêtent les workspaces, et le
  balayeur de RÉTENTION prend le relais (résilié → délai → destruction).

Une résiliation n'est pas une suppression de compte : l'abonnement clos se
reprend (`reprendre()`), le compte demeure — le terme n'y change rien.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from .evenements import publier_evenement_abonnement
from .subscriptions import Subscription, SubscriptionEvent, TransitionRefusee, appliquer

log = structlog.get_logger(__name__)


def cle_terme(abonnement: Subscription) -> str:
    """Clé d'idempotence de la clôture, stable pour une échéance donnée."""
    quand = abonnement.ends_at.isoformat() if abonnement.ends_at else ""
    return f"terme:{abonnement.id}:{quand}"


async def clore_les_termes(maintenant: datetime | None = None) -> int:
    """Une passe : repère les forfaits échus et clôt ceux qui doivent l'être.

    Rend le nombre de clôtures appliquées. Chaque abonnement est traité dans SA
    transaction : le journal (idempotence) et la transition s'écrivent ensemble,
    et un échec sur l'un n'emporte pas les autres.
    """
    from ..db.billing_offers import get_offer
    from ..db.engine import _get_engine
    from ..db.retention import abonnements_a_terme
    from ..db.subscription_events import enregistrer
    from ..db.subscriptions import enregistrer_etat

    quand = maintenant or datetime.now(UTC)
    async with _get_engine().connect() as conn:
        echus = await abonnements_a_terme(conn, maintenant=quand)

    clos = 0
    for abonnement in echus:
        async with _get_engine().begin() as conn:
            offre = await get_offer(abonnement.offer_slug, conn)
            if offre is not None and offre.tacite_reconduction:
                # Le forfait repart : c'est le canal de paiement qui gouverne
                # son cycle (renouvellement, résiliation programmée) — le terme
                # initial n'est pas une fin.
                continue
            evenement = SubscriptionEvent(
                kind="resiliation",
                provider_slug="portail",
                provider_event_id=cle_terme(abonnement),
                login=abonnement.login,
            )
            # Le journal TRANCHE l'idempotence : déjà vu = déjà clos, on passe.
            if not await enregistrer(evenement, abonnement.id, conn):
                continue
            try:
                maj = appliquer(abonnement, evenement, quand)
            except TransitionRefusee:
                # Course avec un webhook qui a clos entre la lecture et ici :
                # rien à faire, l'état voulu est déjà là.
                continue
            await enregistrer_etat(maj, conn)
            await publier_evenement_abonnement(
                "resiliation",
                maj,
                provider_event_id=cle_terme(abonnement),
                conn=conn,
            )
        clos += 1
        log.info(
            "forfait_clos_a_terme",
            subscription_id=abonnement.id,
            owner=abonnement.login,
            offer=abonnement.offer_slug,
            echeance=abonnement.ends_at.isoformat() if abonnement.ends_at else "",
        )
    return clos
