"""Périodes d'inactivité des workspaces (enabler 6016436b) — workspace_idle.

Une ligne = un workspace actuellement inactif (période continue). Supprimée dès
que l'activité reprend, que le workspace est épinglé « garder actif », arrêté ou
injoignable. `alerted_at` non nul = l'alerte de cette période a déjà été émise.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import workspace_idle


async def get_all(conn: AsyncConnection) -> dict[str, dict[str, Any]]:
    rows = (await conn.execute(select(workspace_idle))).mappings().all()
    return {r["ws_id"]: dict(r) for r in rows}


async def get_for_ws(conn: AsyncConnection, ws_id: str) -> dict[str, Any] | None:
    row = (
        (await conn.execute(select(workspace_idle).where(workspace_idle.c.ws_id == ws_id)))
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


async def upsert_idle(
    conn: AsyncConnection,
    ws_id: str,
    login: str,
    idle_since: datetime,
    last_activity: datetime | None,
    now: datetime,
    *,
    reset_alert: bool = False,
) -> None:
    """Crée ou prolonge la période d'inactivité.

    `alerted_at` est préservé par défaut (une seule alerte par période continue) ;
    `reset_alert=True` le réarme — l'appelant le passe quand `idle_since` a avancé,
    c'est-à-dire quand une activité a repris entre deux passes (nouvelle période).
    """
    set_: dict[str, Any] = {
        "login": login,
        "idle_since": idle_since,
        "last_activity": last_activity,
        "updated_at": now,
    }
    if reset_alert:
        set_["alerted_at"] = None
    await conn.execute(
        pg_insert(workspace_idle)
        .values(
            ws_id=ws_id,
            login=login,
            idle_since=idle_since,
            last_activity=last_activity,
            updated_at=now,
        )
        .on_conflict_do_update(index_elements=["ws_id"], set_=set_)
    )


async def mark_alerted(conn: AsyncConnection, ws_id: str, at: datetime) -> None:
    await conn.execute(
        update(workspace_idle).where(workspace_idle.c.ws_id == ws_id).values(alerted_at=at)
    )


async def clear(conn: AsyncConnection, ws_ids: list[str]) -> None:
    """Termine la période d'inactivité (activité, pin, stop, injoignable)."""
    if not ws_ids:
        return
    await conn.execute(delete(workspace_idle).where(workspace_idle.c.ws_id.in_(ws_ids)))
