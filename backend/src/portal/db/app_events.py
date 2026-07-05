"""Journal des événements applicatifs : app_event + app_event_delivery."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import app_event, app_event_delivery


async def insert_event(
    conn: AsyncConnection,
    *,
    event_id: str,
    event_type: str,
    actor: str,
    workspace: str | None,
    subject: dict[str, Any],
    correlation_id: str | None,
    occurred_at: datetime,
) -> None:
    await conn.execute(
        insert(app_event).values(
            id=event_id,
            type=event_type,
            actor=actor,
            workspace=workspace,
            subject=subject,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
        )
    )


async def insert_delivery(
    conn: AsyncConnection,
    *,
    event_id: str,
    listener: str,
    status: str,
    error: str | None,
    detail: Any = None,
) -> None:
    await conn.execute(
        insert(app_event_delivery).values(
            event_id=event_id, listener=listener, status=status, error=error, detail=detail
        )
    )


async def list_events(
    conn: AsyncConnection,
    *,
    actor: str | None = None,
    workspace: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    stmt = select(app_event).order_by(app_event.c.occurred_at.desc()).limit(limit)
    if actor is not None:
        stmt = stmt.where(app_event.c.actor == actor)
    if workspace is not None:
        stmt = stmt.where(app_event.c.workspace == workspace)
    rows = (await conn.execute(stmt)).mappings().all()
    return [dict(r) for r in rows]


async def get_event(conn: AsyncConnection, event_id: str) -> dict[str, Any] | None:
    stmt = select(app_event).where(app_event.c.id == event_id)
    row = (await conn.execute(stmt)).mappings().first()
    return dict(row) if row else None


async def list_deliveries(conn: AsyncConnection, *, event_id: str) -> list[dict[str, Any]]:
    stmt = (
        select(app_event_delivery)
        .where(app_event_delivery.c.event_id == event_id)
        .order_by(app_event_delivery.c.id)
    )
    rows = (await conn.execute(stmt)).mappings().all()
    return [dict(r) for r in rows]


async def list_deliveries_for_events(
    conn: AsyncConnection, event_ids: list[str]
) -> list[dict[str, Any]]:
    """Livraisons de tous les événements donnés en un seul aller-retour (pas de N+1)."""
    if not event_ids:
        return []
    stmt = (
        select(app_event_delivery)
        .where(app_event_delivery.c.event_id.in_(event_ids))
        .order_by(app_event_delivery.c.id)
    )
    rows = (await conn.execute(stmt)).mappings().all()
    return [dict(r) for r in rows]
