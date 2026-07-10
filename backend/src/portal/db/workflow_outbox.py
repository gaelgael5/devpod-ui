"""Couche DB de l'outbox du relais d'events workflow (workflow_event_outbox).

Rôles séparés : l'écouteur du bus n'appelle que `enqueue` (dans sa txn) ; le
worker de fond appelle `claim_due` puis, après le POST réseau (HORS txn), l'un
des `mark_*`. `purge_delivered` tient la table propre.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import workflow_event_outbox as _outbox


async def enqueue(conn: AsyncConnection, *, event_id: str, event_code: str, raw_body: str) -> None:
    """Insère une enveloppe à livrer (status 'pending', dû immédiatement)."""
    await conn.execute(
        insert(_outbox).values(event_id=event_id, event_code=event_code, raw_body=raw_body)
    )


async def claim_due(conn: AsyncConnection, *, now: datetime, limit: int) -> list[dict[str, Any]]:
    """Lignes 'pending' dont next_attempt_at <= now, les plus anciennes d'abord."""
    stmt = (
        select(_outbox)
        .where(_outbox.c.status == "pending")
        .where(_outbox.c.next_attempt_at <= now)
        .order_by(_outbox.c.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    rows = (await conn.execute(stmt)).mappings().all()
    return [dict(r) for r in rows]


async def mark_delivered(conn: AsyncConnection, row_id: int) -> None:
    """Marque une ligne livrée (status 'delivered', delivered_at = now())."""
    await conn.execute(
        update(_outbox)
        .where(_outbox.c.id == row_id)
        .values(status="delivered", delivered_at=func.now())
    )


async def mark_retry(
    conn: AsyncConnection,
    row_id: int,
    *,
    error: str,
    attempts: int,
    next_attempt_at: datetime,
) -> None:
    """Reprogramme une ligne (reste 'pending') après un échec transitoire."""
    await conn.execute(
        update(_outbox)
        .where(_outbox.c.id == row_id)
        .values(attempts=attempts, last_error=error, next_attempt_at=next_attempt_at)
    )


async def mark_failed(conn: AsyncConnection, row_id: int, *, error: str, attempts: int) -> None:
    """Abandon définitif d'une ligne (status 'failed') après épuisement des essais."""
    await conn.execute(
        update(_outbox)
        .where(_outbox.c.id == row_id)
        .values(status="failed", attempts=attempts, last_error=error)
    )


async def purge_delivered(conn: AsyncConnection, *, older_than: datetime) -> int:
    """Supprime les lignes 'delivered' livrées avant `older_than`. Retourne le count."""
    result = await conn.execute(
        delete(_outbox)
        .where(_outbox.c.status == "delivered")
        .where(_outbox.c.delivered_at < older_than)
    )
    return int(result.rowcount or 0)
