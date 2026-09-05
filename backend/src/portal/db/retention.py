"""Repérage des abonnements dont le délai de rétention est écoulé.

Ce module écrit et lit ; la décision — quels délais, quel événement émettre —
vit dans `billing.retention`. Deux garanties portées ICI, par la base :

- `abonnements_en_retard` ne rend que les épisodes **jamais notifiés** : la
  jointure d'exclusion sur `retention_notifications` fait le tri, pas un état
  en mémoire qui ne survivrait pas à un redémarrage ;
- `marquer_notifie` tranche l'idempotence par la contrainte d'unicité
  (`ON CONFLICT DO NOTHING`), pas par une lecture préalable : deux passes
  concurrentes du balayeur ne notifient qu'une fois.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from ..billing.config import PolitiqueRetention
from ..billing.subscriptions import Subscription
from .subscriptions import _row_to_subscription
from .tables import retention_notifications, subscriptions


async def abonnements_en_retard(
    conn: AsyncConnection, *, maintenant: datetime, politique: PolitiqueRetention
) -> list[Subscription]:
    """Les abonnements en fin de vie dont le délai est écoulé, jamais notifiés.

    Chaque état a SON délai — c'est la règle de la fiche : un échec de paiement
    et une résiliation ne laissent pas le même temps avant destruction.
    """
    cut_echec = maintenant - timedelta(days=politique.echec_paiement_jours)
    cut_resilie = maintenant - timedelta(days=politique.resiliation_jours)
    deja = retention_notifications
    stmt = (
        select(subscriptions)
        .outerjoin(
            deja,
            and_(
                deja.c.subscription_id == subscriptions.c.id,
                deja.c.state == subscriptions.c.state,
                deja.c.state_changed_at == subscriptions.c.state_changed_at,
            ),
        )
        .where(
            deja.c.id.is_(None),
            or_(
                and_(
                    subscriptions.c.state == "echec_paiement",
                    subscriptions.c.state_changed_at <= cut_echec,
                ),
                and_(
                    subscriptions.c.state == "resilie",
                    subscriptions.c.state_changed_at <= cut_resilie,
                ),
            ),
        )
        .order_by(subscriptions.c.state_changed_at)
    )
    rows = (await conn.execute(stmt)).mappings().all()
    return [_row_to_subscription(dict(r)) for r in rows]


async def marquer_notifie(
    conn: AsyncConnection,
    *,
    subscription_id: str,
    state: str,
    state_changed_at: datetime,
) -> bool:
    """Réserve l'épisode. Rend `False` s'il était déjà notifié.

    L'appelant n'émet l'événement que si cette fonction rend `True`, dans la
    même transaction : c'est ce qui interdit la double notification — et donc
    la double destruction — que la fiche pointe comme LE défaut à ne pas avoir.
    """
    resultat = await conn.execute(
        pg_insert(retention_notifications)
        .values(
            subscription_id=subscription_id,
            state=state,
            state_changed_at=state_changed_at,
        )
        .on_conflict_do_nothing(constraint="uq_retention_notification_episode")
    )
    return bool(resultat.rowcount)
