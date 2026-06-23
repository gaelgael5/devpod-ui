from __future__ import annotations

from typing import Any

import structlog
from mcp import ClientSession
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db import mcp_catalog as cat_db
from .client import fetch_primitives

_log = structlog.get_logger(__name__)

_KINDS = ("tool", "resource", "prompt")


async def sync_backend(
    conn: AsyncConnection, *, backend_id: str, session: ClientSession
) -> dict[str, Any]:
    """Synchronise les primitives d'un backend dans mcp_tool_catalog.

    Upsert chaque primitive (détection de redéfinition → quarantaine collante),
    puis supprime du catalogue celles qui ne sont plus publiées.
    """
    primitives = await fetch_primitives(session)

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

    for kind in _KINDS:
        await cat_db.prune_absent(conn, backend_id, kind, present[kind])

    _log.info("mcp_catalog_synced", backend_id=backend_id, count=len(primitives))
    return {"synced": len(primitives), "quarantined": quarantined}
