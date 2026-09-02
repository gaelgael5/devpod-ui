"""Journal des événements reçus d'un canal de vente, et leur idempotence.

La table existe depuis la migration 111 avec sa contrainte d'unicité ; ce module
lui donne enfin des appelants.

Un webhook se rejoue. Le fournisseur réémet quand il n'a pas eu de 2xx, et il
réémet aussi sans raison apparente. Sans garde, un renouvellement traité deux
fois avance deux fois l'abonnement.

**L'idempotence est portée par la contrainte d'unicité, pas par un `SELECT`
préalable.** Deux réémissions arrivent souvent en rafale, et le temps entre la
lecture et l'écriture suffit à les laisser passer toutes les deux. On insère, et
c'est la base qui tranche.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ..billing.subscriptions import SubscriptionEvent
from .tables import subscription_events


async def enregistrer(
    event: SubscriptionEvent,
    subscription_id: str | None,
    conn: AsyncConnection,
) -> bool:
    """Journalise l'événement. Rend `False` s'il avait déjà été vu.

    L'appelant ne doit appliquer la transition que si cette fonction rend
    `True` — et dans la MÊME transaction, sinon un incident entre les deux
    laisserait un événement marqué traité sans l'avoir été.

    Le `savepoint` est nécessaire : sur PostgreSQL, une violation de contrainte
    avorte la transaction entière. Sans lui, le rejeu — cas NORMAL et fréquent —
    empêcherait toute écriture ultérieure dans la même transaction.
    """
    try:
        async with conn.begin_nested():
            await conn.execute(
                subscription_events.insert().values(
                    provider_slug=event.provider_slug,
                    provider_event_id=event.provider_event_id,
                    kind=event.kind,
                    subscription_id=subscription_id,
                    login=event.login,
                    payload=dict(event.payload),
                    # NOT NULL en base : l'instant de RECEPTION fait foi quand
                    # le fournisseur n'a pas date son evenement.
                    occurred_at=event.occurred_at or datetime.now(UTC),
                )
            )
    except IntegrityError:
        return False
    return True


async def deja_vu(provider_slug: str, provider_event_id: str, conn: AsyncConnection) -> bool:
    """Lecture seule, pour les écrans et le diagnostic.

    **Ne pas s'en servir comme garde d'idempotence** : entre cette lecture et
    l'écriture, une seconde réémission passe. C'est `enregistrer` qui tranche.
    """
    stmt = select(subscription_events.c.id).where(
        subscription_events.c.provider_slug == provider_slug,
        subscription_events.c.provider_event_id == provider_event_id,
    )
    return (await conn.execute(stmt)).first() is not None


async def historique(subscription_id: str, conn: AsyncConnection) -> list[dict[str, object]]:
    """Événements d'un abonnement, du plus ancien au plus récent.

    L'ordre chronologique n'est pas cosmétique : c'est la lecture d'un cycle de
    vie, et l'inverser rendrait la séquence incompréhensible.
    """
    stmt = (
        select(
            subscription_events.c.kind,
            subscription_events.c.provider_event_id,
            subscription_events.c.occurred_at,
            subscription_events.c.created_at,
        )
        .where(subscription_events.c.subscription_id == subscription_id)
        .order_by(subscription_events.c.created_at, subscription_events.c.id)
    )
    rows = (await conn.execute(stmt)).mappings().all()
    return [dict(r) for r in rows]


async def dernier_recu(provider_slug: str, conn: AsyncConnection) -> datetime | None:
    """Instant du dernier événement reçu de ce canal.

    Sert à voir qu'un canal s'est TU : un webhook qui ne parvient plus ne
    produit aucune erreur, il produit du silence — et le silence ressemble à un
    système en bon ordre.
    """
    stmt = (
        select(subscription_events.c.created_at)
        .where(subscription_events.c.provider_slug == provider_slug)
        .order_by(subscription_events.c.created_at.desc())
        .limit(1)
    )
    return (await conn.execute(stmt)).scalars().first()
