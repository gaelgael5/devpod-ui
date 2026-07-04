from __future__ import annotations

from typing import Any

import structlog
from mcp import ClientSession
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db import mcp_catalog as cat_db
from .client import advertised_kinds, fetch_primitives

_log = structlog.get_logger(__name__)

_KINDS = ("tool", "resource", "prompt")


async def fetch_backend_catalog(
    session: ClientSession,
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    """Interroge le backend (réseau seul, aucune I/O DB) : primitives + kinds annoncés."""
    primitives = await fetch_primitives(session)
    caps = session.get_server_capabilities()
    kinds = advertised_kinds(caps)
    return primitives, kinds


async def write_backend_catalog(
    conn: AsyncConnection,
    *,
    backend_id: str,
    primitives: list[dict[str, Any]],
    kinds: tuple[str, ...],
) -> dict[str, Any]:
    """Upsert les primitives déjà récupérées dans mcp_tool_catalog (DB seule, pas de réseau).

    À appeler dans une transaction courte, après fetch_backend_catalog (bug 026 :
    l'I/O réseau ne doit jamais se faire à l'intérieur d'une transaction DB).
    """
    quarantined: list[str] = []
    present: dict[str, list[str]] = {k: [] for k in _KINDS}
    for p in primitives:
        present[p["kind"]].append(p["original_name"])
        flagged = await cat_db.upsert_primitive(
            conn,
            backend_id=backend_id,
            kind=p["kind"],
            original_name=p["original_name"],
            definition=p["definition"],
            definition_hash=p["definition_hash"],
        )
        if flagged:
            quarantined.append(p["original_name"])

    for kind in kinds:
        await cat_db.prune_absent(conn, backend_id, kind, present[kind])

    if quarantined:
        _log.warning("mcp_catalog_quarantined", backend_id=backend_id, names=quarantined)
    _log.info("mcp_catalog_synced", backend_id=backend_id, count=len(primitives))
    return {"synced": len(primitives), "quarantined": quarantined}


async def sync_backend(
    conn: AsyncConnection, *, backend_id: str, session: ClientSession
) -> dict[str, Any]:
    """Synchronise les primitives d'un backend dans mcp_tool_catalog.

    Upsert chaque primitive (détection de redéfinition → quarantaine collante),
    puis supprime du catalogue celles qui ne sont plus publiées. Combine
    fetch_backend_catalog (réseau) + write_backend_catalog (DB) dans le `conn`
    fourni par l'appelant — utilisé quand réseau et écriture partagent
    volontairement une même connexion (ex. /probe, un seul backend à la fois).
    """
    primitives, kinds = await fetch_backend_catalog(session)
    return await write_backend_catalog(
        conn, backend_id=backend_id, primitives=primitives, kinds=kinds
    )
