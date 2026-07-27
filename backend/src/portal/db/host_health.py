"""État de vivacité des hosts (enabler 727ee81d), posé par nodes/liveness.py.

`reachable` NULL = jamais sondé ; `last_seen` = dernière sonde réussie ;
`changed_at` = entrée dans l'état courant (transition).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import host_health


async def get_all(conn: AsyncConnection) -> dict[str, dict[str, Any]]:
    rows = (await conn.execute(select(host_health))).mappings().all()
    return {r["name"]: dict(r) for r in rows}


async def record_success(
    conn: AsyncConnection, name: str, now: datetime, *, transitioned: bool
) -> None:
    values: dict[str, Any] = {"name": name, "reachable": True, "last_seen": now}
    if transitioned:
        values["changed_at"] = now
    set_ = {k: v for k, v in values.items() if k != "name"}
    await conn.execute(
        pg_insert(host_health)
        .values(**values)
        .on_conflict_do_update(index_elements=["name"], set_=set_)
    )


async def record_unreachable(conn: AsyncConnection, name: str, now: datetime) -> None:
    """Bascule en injoignable — appelée uniquement sur transition (hystérésis amont)."""
    await conn.execute(
        pg_insert(host_health)
        .values(name=name, reachable=False, changed_at=now)
        .on_conflict_do_update(
            index_elements=["name"], set_={"reachable": False, "changed_at": now}
        )
    )


async def prune_absent(conn: AsyncConnection, names: set[str]) -> None:
    """Purge l'état des hosts retirés de la config (pas de ligne orpheline)."""
    stmt = delete(host_health)
    if names:
        stmt = stmt.where(host_health.c.name.notin_(names))
    await conn.execute(stmt)
