"""Couche DB des automates (`automation`, `_scope`, `_header`, `_cursor`).

Un automate consomme le journal `app_event` par curseur et appelle une opération
d'un contrat OpenAPI. Portées multi-workspaces, en-têtes value XOR secret_ref,
ordre d'évaluation (position) + stop_chain. La transaction appartient à l'appelant.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import automation as _a
from .tables import automation_cursor as _cur
from .tables import automation_header as _h
from .tables import automation_scope as _s

# Champs modifiables d'un automate (hors id / timestamps).
_EDITABLE = (
    "label",
    "active",
    "position",
    "stop_chain",
    "event_types",
    "delay_minutes",
    "contract_ref",
    "operation_id",
    "url",
    "http_method",
    "body_template",
)


async def create(conn: AsyncConnection, **fields: Any) -> dict[str, Any]:
    """Crée un automate (désactivé par défaut). `fields` = sous-ensemble de _EDITABLE."""
    values = {k: v for k, v in fields.items() if k in _EDITABLE}
    values["id"] = uuid.uuid4().hex
    stmt = insert(_a).values(**values).returning(_a)
    return dict((await conn.execute(stmt)).mappings().one())


async def update_fields(
    conn: AsyncConnection, automation_id: str, **fields: Any
) -> dict[str, Any] | None:
    """Met à jour les champs fournis (parmi _EDITABLE). None si absent."""
    values = {k: v for k, v in fields.items() if k in _EDITABLE and v is not None}
    if not values:
        return await get(conn, automation_id)
    values["updated_at"] = func.now()
    stmt = update(_a).where(_a.c.id == automation_id).values(**values).returning(_a)
    row = (await conn.execute(stmt)).mappings().first()
    return dict(row) if row is not None else None


async def get(conn: AsyncConnection, automation_id: str) -> dict[str, Any] | None:
    row = (await conn.execute(select(_a).where(_a.c.id == automation_id))).mappings().first()
    return dict(row) if row is not None else None


async def delete_automation(conn: AsyncConnection, automation_id: str) -> bool:
    result = await conn.execute(delete(_a).where(_a.c.id == automation_id))
    return bool(result.rowcount)


async def list_all(conn: AsyncConnection) -> list[dict[str, Any]]:
    """Tous les automates, ordre d'évaluation (position), détails attachés."""
    rows = (await conn.execute(select(_a).order_by(_a.c.position, _a.c.id))).mappings().all()
    return [await _attach_details(conn, dict(r)) for r in rows]


async def list_active(conn: AsyncConnection) -> list[dict[str, Any]]:
    """Automates actifs, ordre d'évaluation, détails attachés (pour le runner)."""
    stmt = select(_a).where(_a.c.active.is_(True)).order_by(_a.c.position, _a.c.id)
    rows = (await conn.execute(stmt)).mappings().all()
    return [await _attach_details(conn, dict(r)) for r in rows]


async def max_position(conn: AsyncConnection) -> int:
    stmt = select(func.coalesce(func.max(_a.c.position), -1))
    return int((await conn.execute(stmt)).scalar_one())


async def reorder(conn: AsyncConnection, ordered_ids: list[str]) -> None:
    """Réécrit `position` selon l'ordre fourni (drag&drop)."""
    for pos, automation_id in enumerate(ordered_ids):
        await conn.execute(
            update(_a).where(_a.c.id == automation_id).values(position=pos, updated_at=func.now())
        )


# ─── Portées ──────────────────────────────────────────────────────────────────


async def get_scopes(conn: AsyncConnection, automation_id: str) -> list[str]:
    stmt = (
        select(_s.c.workspace)
        .where(_s.c.automation_id == automation_id)
        .order_by(_s.c.workspace)
    )
    return [r[0] for r in (await conn.execute(stmt)).all()]


async def set_scopes(conn: AsyncConnection, automation_id: str, workspaces: list[str]) -> None:
    """Remplace la portée (au moins une entrée ; '*' = tous). Dédupliqué."""
    await conn.execute(delete(_s).where(_s.c.automation_id == automation_id))
    seen: set[str] = set()
    for ws in workspaces:
        if ws and ws not in seen:
            seen.add(ws)
            await conn.execute(insert(_s).values(automation_id=automation_id, workspace=ws))


# ─── En-têtes ───────────────────────────────────────────────────────────────


async def get_headers(conn: AsyncConnection, automation_id: str) -> list[dict[str, Any]]:
    stmt = select(_h).where(_h.c.automation_id == automation_id).order_by(_h.c.name)
    return [dict(r) for r in (await conn.execute(stmt)).mappings().all()]


async def set_headers(
    conn: AsyncConnection, automation_id: str, headers: list[dict[str, Any]]
) -> None:
    """Remplace les en-têtes. Chaque entrée : name + (value XOR secret_ref)."""
    await conn.execute(delete(_h).where(_h.c.automation_id == automation_id))
    for hdr in headers:
        await conn.execute(
            insert(_h).values(
                id=uuid.uuid4().hex,
                automation_id=automation_id,
                name=hdr["name"],
                value=hdr.get("value"),
                secret_ref=hdr.get("secret_ref"),
            )
        )


# ─── Curseur ──────────────────────────────────────────────────────────────────


async def get_cursor(conn: AsyncConnection, automation_id: str) -> int:
    """Position du curseur (0 si jamais initialisé)."""
    stmt = select(_cur.c.last_seq).where(_cur.c.automation_id == automation_id)
    row = (await conn.execute(stmt)).scalar_one_or_none()
    return int(row) if row is not None else 0


async def set_cursor(conn: AsyncConnection, automation_id: str, last_seq: int) -> None:
    """Upsert du curseur à `last_seq`."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stmt = pg_insert(_cur).values(automation_id=automation_id, last_seq=last_seq)
    stmt = stmt.on_conflict_do_update(
        index_elements=[_cur.c.automation_id],
        set_={"last_seq": last_seq, "updated_at": func.now()},
    )
    await conn.execute(stmt)


async def _attach_details(conn: AsyncConnection, row: dict[str, Any]) -> dict[str, Any]:
    """Enrichit un automate de ses en-têtes et curseur."""
    row["headers"] = await get_headers(conn, row["id"])
    row["last_seq"] = await get_cursor(conn, row["id"])
    return row
