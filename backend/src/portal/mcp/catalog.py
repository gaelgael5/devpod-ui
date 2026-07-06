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
    protect_quarantine: bool = True,
    trigger: str = "unknown",
) -> dict[str, Any]:
    """Upsert les primitives déjà récupérées dans mcp_tool_catalog (DB seule, pas de réseau).

    À appeler dans une transaction courte, après fetch_backend_catalog (bug 026 :
    l'I/O réseau ne doit jamais se faire à l'intérieur d'une transaction DB).
    L'appelant porte la transaction : l'écriture est atomique (upserts + prunes
    committés ensemble, rollback intégral sur exception à mi-parcours).

    `protect_quarantine=False` (backend `quarantine_disabled`) : les redéfinitions
    ne quarantinent plus et les quarantaines héritées sont levées à l'upsert.

    Chaque resync émet `mcp_catalog_resync` : déclencheur, comptes avant/reçu/après
    et delta nominatif (`kind:nom`) — un resync qui retire une primitive est visible.
    """
    before = await cat_db.list_catalog_names(conn, backend_id)
    before_keys = {(r["kind"], r["original_name"]) for r in before}

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
            protect=protect_quarantine,
        )
        if flagged:
            quarantined.append(p["original_name"])

    for kind in kinds:
        await cat_db.prune_absent(conn, backend_id, kind, present[kind])

    after = await cat_db.list_catalog_names(conn, backend_id)
    after_keys = {(r["kind"], r["original_name"]) for r in after}
    added = sorted(f"{k}:{n}" for k, n in after_keys - before_keys)
    removed = sorted(f"{k}:{n}" for k, n in before_keys - after_keys)
    still_quarantined = sorted(
        f"{r['kind']}:{r['original_name']}" for r in after if r["quarantined"]
    )

    _log.info(
        "mcp_catalog_resync",
        backend_id=backend_id,
        trigger=trigger,
        before=len(before),
        received=len(primitives),
        after=len(after),
        added=added,
        removed=removed,
    )
    if removed:
        _log.warning(
            "mcp_catalog_pruned", backend_id=backend_id, trigger=trigger, removed=removed
        )
    if still_quarantined:
        # Re-loggé à CHAQUE resync (pas seulement au flag initial) : une primitive
        # masquée par quarantaine doit rester visible dans les logs — c'est le
        # silence de ce cas qui a rendu le bug create_document indétectable.
        _log.warning(
            "mcp_catalog_quarantined", backend_id=backend_id, names=still_quarantined
        )
    _log.info("mcp_catalog_synced", backend_id=backend_id, count=len(primitives))
    return {"synced": len(primitives), "quarantined": quarantined}


async def sync_backend(
    conn: AsyncConnection,
    *,
    backend_id: str,
    session: ClientSession,
    protect_quarantine: bool = True,
    trigger: str = "unknown",
) -> dict[str, Any]:
    """Synchronise les primitives d'un backend dans mcp_tool_catalog.

    Upsert chaque primitive (détection de redéfinition → quarantaine collante,
    sauf `protect_quarantine=False`), puis supprime du catalogue celles qui ne
    sont plus publiées. Combine fetch_backend_catalog (réseau) +
    write_backend_catalog (DB) dans le `conn` fourni par l'appelant — utilisé
    quand réseau et écriture partagent volontairement une même connexion
    (ex. /probe, un seul backend à la fois).
    """
    primitives, kinds = await fetch_backend_catalog(session)
    return await write_backend_catalog(
        conn,
        backend_id=backend_id,
        primitives=primitives,
        kinds=kinds,
        protect_quarantine=protect_quarantine,
        trigger=trigger,
    )
