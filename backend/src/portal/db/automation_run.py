"""Couche DB des exécutions d'automates (`automation_run`).

Anti-rejeu : `claim` insère une trace « running » avec ON CONFLICT DO NOTHING sur
l'index unique partiel (automation_id, dedup_key) des runs automatiques — un
automate ne traite qu'une fois une version donnée. Le curseur n'avance qu'après
`finish` : un crash entre claim et finish laisse une trace « running » que
`reset_stale_running` (au démarrage) nettoie pour permettre le rejeu (at-least-once).
Les rejeus manuels (`manual=true`) échappent à l'unicité.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import automation_run as _r

_PREVIEW_MAX = 2000


def _clip(value: str | None) -> str | None:
    if value is None:
        return None
    return value if len(value) <= _PREVIEW_MAX else value[:_PREVIEW_MAX] + "…"


async def claim(
    conn: AsyncConnection, *, automation_id: str, event_seq: int, dedup_key: str
) -> str | None:
    """Réserve un run automatique. Retourne son id, ou None si déjà traité (conflit)."""
    run_id = uuid.uuid4().hex
    stmt = (
        pg_insert(_r)
        .values(
            id=run_id,
            automation_id=automation_id,
            event_seq=event_seq,
            dedup_key=dedup_key,
            status="running",
            manual=False,
        )
        .on_conflict_do_nothing(
            index_elements=[_r.c.automation_id, _r.c.dedup_key],
            index_where=text("manual = false"),
        )
        .returning(_r.c.id)
    )
    return (await conn.execute(stmt)).scalar_one_or_none()


async def finish(
    conn: AsyncConnection,
    run_id: str,
    *,
    status: str,
    http_status: int | None = None,
    request_preview: str | None = None,
    response_preview: str | None = None,
    error: str | None = None,
    trace: list[dict[str, Any]] | None = None,
) -> None:
    """Clôt un run (ok | failed | skipped) avec ses aperçus bornés + trace d'arbre."""
    await conn.execute(
        update(_r)
        .where(_r.c.id == run_id)
        .values(
            status=status,
            http_status=http_status,
            request_preview=_clip(request_preview),
            response_preview=_clip(response_preview),
            error=_clip(error),
            trace=trace,
        )
    )


async def record_manual(
    conn: AsyncConnection,
    *,
    automation_id: str,
    event_seq: int,
    dedup_key: str,
    status: str,
    http_status: int | None = None,
    request_preview: str | None = None,
    response_preview: str | None = None,
    error: str | None = None,
    trace: list[dict[str, Any]] | None = None,
) -> str:
    """Insère un run de rejeu manuel (hors unicité anti-rejeu). Retourne son id."""
    run_id = uuid.uuid4().hex
    await conn.execute(
        insert(_r).values(
            id=run_id,
            automation_id=automation_id,
            event_seq=event_seq,
            dedup_key=dedup_key,
            status=status,
            http_status=http_status,
            request_preview=_clip(request_preview),
            response_preview=_clip(response_preview),
            error=_clip(error),
            trace=trace,
            manual=True,
        )
    )
    return run_id


async def get_run(conn: AsyncConnection, run_id: str) -> dict[str, Any] | None:
    row = (await conn.execute(select(_r).where(_r.c.id == run_id))).mappings().first()
    return dict(row) if row is not None else None


async def list_for_automation(
    conn: AsyncConnection, automation_id: str, *, limit: int = 20
) -> list[dict[str, Any]]:
    """Historique d'un automate, plus récent d'abord."""
    stmt = (
        select(_r)
        .where(_r.c.automation_id == automation_id)
        .order_by(_r.c.created_at.desc(), _r.c.id.desc())
        .limit(limit)
    )
    return [dict(r) for r in (await conn.execute(stmt)).mappings().all()]


async def prune(conn: AsyncConnection, automation_id: str, *, keep: int) -> int:
    """Ne garde que les `keep` runs les plus récents d'un automate. Retourne le count purgé."""
    keep_ids = select(_r.c.id).where(_r.c.automation_id == automation_id).order_by(
        _r.c.created_at.desc(), _r.c.id.desc()
    ).limit(keep)
    result = await conn.execute(
        delete(_r).where(_r.c.automation_id == automation_id).where(_r.c.id.not_in(keep_ids))
    )
    return int(result.rowcount or 0)


async def clear(conn: AsyncConnection, automation_id: str) -> int:
    """Vide l'historique d'un automate. Retourne le count supprimé."""
    result = await conn.execute(delete(_r).where(_r.c.automation_id == automation_id))
    return int(result.rowcount or 0)


async def clear_after_seq(conn: AsyncConnection, after_seq: int) -> int:
    """Supprime les runs des events de seq > `after_seq` (tous automates confondus).

    Sert au repositionnement du curseur : purger l'anti-rejeu pour que ces events
    soient ré-évalués quand le curseur repasse dessus. Retourne le count supprimé.
    """
    result = await conn.execute(delete(_r).where(_r.c.event_seq > after_seq))
    return int(result.rowcount or 0)


async def purge_older_than(conn: AsyncConnection, older_than: datetime) -> int:
    """Rétention : supprime les runs plus anciens que `older_than`. Retourne le count."""
    result = await conn.execute(delete(_r).where(_r.c.created_at < older_than))
    return int(result.rowcount or 0)


async def reset_stale_running(conn: AsyncConnection) -> int:
    """Supprime les traces « running » orphelines (crash entre claim et finish).

    Le curseur n'a pas avancé au-delà de leur event : les supprimer permet le
    rejeu automatique au prochain balayage (at-least-once). Retourne le count.
    """
    result = await conn.execute(delete(_r).where(_r.c.status == "running"))
    return int(result.rowcount or 0)


async def count(conn: AsyncConnection, automation_id: str) -> int:
    stmt = select(func.count()).select_from(_r).where(_r.c.automation_id == automation_id)
    return int((await conn.execute(stmt)).scalar_one())
