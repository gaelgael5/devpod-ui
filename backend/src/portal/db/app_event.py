"""Couche DB du journal durable des events (`app_event`).

Journal append-only : `append` insère un fait (dans la transaction fournie par
l'appelant — jamais de commit ici) ; les automates consomment par curseur via
`read_after` en gardant leur propre `last_seq`. Aucune dédup à l'insertion : le
journal enregistre tous les faits, l'idempotence est portée en aval par
`automation_run` (once-per-version).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import app_event as _ev


async def append(
    conn: AsyncConnection,
    *,
    event_id: str,
    event_type: str,
    actor: str,
    occurred_at: datetime,
    workspace: str | None = None,
    subject: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    dedup_key: str | None = None,
) -> int:
    """Appende un event au journal et retourne son `seq` (ordre total).

    L'insertion se fait dans la transaction de `conn` : si l'appelant tient la
    transaction de la mutation métier, l'event est atomique avec elle.
    """
    stmt = (
        insert(_ev)
        .values(
            event_id=event_id,
            event_type=event_type,
            actor=actor,
            workspace=workspace,
            subject=subject or {},
            correlation_id=correlation_id,
            dedup_key=dedup_key,
            occurred_at=occurred_at,
        )
        .returning(_ev.c.seq)
    )
    return int((await conn.execute(stmt)).scalar_one())


async def read_after(
    conn: AsyncConnection,
    *,
    after_seq: int,
    limit: int,
    event_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Events de `seq` strictement > `after_seq`, ordre croissant (curseur automate)."""
    stmt = select(_ev).where(_ev.c.seq > after_seq).order_by(_ev.c.seq).limit(limit)
    if event_types:
        stmt = stmt.where(_ev.c.event_type.in_(event_types))
    rows = (await conn.execute(stmt)).mappings().all()
    return [dict(r) for r in rows]


async def count_after(
    conn: AsyncConnection,
    *,
    after_seq: int,
    event_types: list[str] | None = None,
) -> int:
    """Nombre d'events en attente au-delà du curseur (badge « N en attente »)."""
    stmt = select(func.count()).select_from(_ev).where(_ev.c.seq > after_seq)
    if event_types:
        stmt = stmt.where(_ev.c.event_type.in_(event_types))
    return int((await conn.execute(stmt)).scalar_one())


async def latest_seq(conn: AsyncConnection) -> int:
    """Plus grand `seq` du journal (0 si vide) — init de curseur / borne backfill."""
    stmt = select(func.coalesce(func.max(_ev.c.seq), 0))
    return int((await conn.execute(stmt)).scalar_one())


async def get(conn: AsyncConnection, seq: int) -> dict[str, Any] | None:
    """Lit un event par `seq` (rejeu / injection). None si absent."""
    row = (await conn.execute(select(_ev).where(_ev.c.seq == seq))).mappings().first()
    return dict(row) if row is not None else None


async def mark_consumed(conn: AsyncConnection, *, seq: int, consumer: str) -> None:
    """Marque un event consommé (chaînage stop_chain du moteur d'automates)."""
    await conn.execute(update(_ev).where(_ev.c.seq == seq).values(consumed_by=consumer))


async def purge_older_than(conn: AsyncConnection, *, older_than: datetime) -> int:
    """Purge les events plus vieux que `older_than` (rétention). Retourne le count."""
    result = await conn.execute(delete(_ev).where(_ev.c.created_at < older_than))
    return int(result.rowcount or 0)
