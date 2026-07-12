"""Endpoints REST du journal d'événements applicatifs (hub Services & Security).

Lecture seule + rejeu : les événements sont émis par les couches service, jamais
par cette API. Le rejeu re-dispatche un événement existant vers ses écouteurs
(idempotents par construction) — l'événement n'est pas réinséré, les nouvelles
livraisons s'ajoutent à l'historique.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..db import app_events as db
from ..db.engine import get_conn
from ..events.bus import get_bus
from ..events.models import AppEvent

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["events"])


def _with_deliveries(
    events: list[dict[str, Any]], deliveries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_event: dict[str, list[dict[str, Any]]] = {}
    for d in deliveries:
        by_event.setdefault(d["event_id"], []).append(d)
    return [{**e, "deliveries": by_event.get(e["id"], [])} for e in events]


@router.get("/events")
async def list_events_route(
    workspace: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    events = await db.list_events(conn, actor=user.login, workspace=workspace, limit=limit)
    deliveries = await db.list_deliveries_for_events(conn, [e["id"] for e in events])
    return _with_deliveries(events, deliveries)


@router.post("/events/{event_id}/replay", status_code=202)
async def replay_event_route(
    event_id: str,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    row = await db.get_event(conn, event_id)
    # 404 aussi pour un événement d'un autre utilisateur : ne pas révéler son existence.
    if row is None or row["actor"] != user.login:
        raise HTTPException(status_code=404, detail="événement introuvable")
    event = AppEvent(
        event_id=row["id"],
        type=row["type"],
        occurred_at=row["occurred_at"],
        actor=row["actor"],
        workspace=row["workspace"],
        subject=row["subject"],
        correlation_id=row["correlation_id"],
    )
    await get_bus().redeliver(event)
    _log.info("event_replay_requested", event_id=event_id, login=user.login)
    return {"replayed": event_id}
