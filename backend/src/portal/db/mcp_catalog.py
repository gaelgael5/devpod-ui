from __future__ import annotations

from typing import Any

from sqlalchemy import and_, delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import mcp_tool_catalog as cat

_COLS = [
    cat.c.backend_id,
    cat.c.kind,
    cat.c.original_name,
    cat.c.definition,
    cat.c.definition_hash,
    cat.c.first_seen,
    cat.c.last_seen,
    cat.c.quarantined,
]


async def upsert_primitive(
    conn: AsyncConnection,
    *,
    backend_id: str,
    kind: str,
    original_name: str,
    definition: dict[str, Any],
    definition_hash: str,
) -> bool:
    """Insère/met à jour une primitive dans le catalogue.

    Retourne True si une redéfinition (hash différent d'une entrée existante)
    est détectée → mise en quarantaine collante.
    Une fois quarantinée, la primitive reste quarantinée jusqu'à un appel
    explicite à set_quarantine(False).
    """
    from sqlalchemy import func as _func

    existing = (
        await conn.execute(
            select(cat.c.definition_hash, cat.c.quarantined).where(
                cat.c.backend_id == backend_id,
                cat.c.kind == kind,
                cat.c.original_name == original_name,
            )
        )
    ).first()

    quarantine = existing is not None and existing[0] != definition_hash

    stmt = pg_insert(cat).values(
        backend_id=backend_id,
        kind=kind,
        original_name=original_name,
        definition=definition,
        definition_hash=definition_hash,
        quarantined=quarantine,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="pk_mcp_tool_catalog",
        set_={
            "definition": definition,
            "definition_hash": definition_hash,
            "last_seen": _func.now(),
            # Quarantaine collante : OR bit-à-bit entre l'état existant et le nouveau flag.
            # Une primitive quarantinée reste quarantinée même si le hash revient au nominal.
            "quarantined": cat.c.quarantined | quarantine,
        },
    )
    await conn.execute(stmt)
    return quarantine


async def list_primitives(
    conn: AsyncConnection, backend_id: str, kind: str
) -> list[dict[str, Any]]:
    q = (
        select(*_COLS)
        .where(cat.c.backend_id == backend_id, cat.c.kind == kind)
        .order_by(cat.c.original_name)
    )
    return [dict(r) for r in (await conn.execute(q)).mappings().all()]


async def set_quarantine(
    conn: AsyncConnection,
    backend_id: str,
    kind: str,
    original_name: str,
    value: bool,
) -> None:
    await conn.execute(
        update(cat)
        .where(
            cat.c.backend_id == backend_id,
            cat.c.kind == kind,
            cat.c.original_name == original_name,
        )
        .values(quarantined=value)
    )


async def prune_absent(
    conn: AsyncConnection,
    backend_id: str,
    kind: str,
    present_names: list[str],
) -> None:
    """Supprime toutes les primitives de (backend_id, kind) absentes de present_names."""
    await conn.execute(
        delete(cat).where(
            and_(
                cat.c.backend_id == backend_id,
                cat.c.kind == kind,
                cat.c.original_name.notin_(present_names),
            )
        )
    )
