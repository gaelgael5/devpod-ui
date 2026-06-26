"""Enregistrement idempotent du backend MCP interne `devpod` au démarrage.

Un backend `devpod` par user réel (modèle per-owner existant) : id=`devpod-{login}`,
namespace `devpod`, transport `internal`, url vide. Le catalogue est peuplé depuis
le registre `DEVPOD_PRIMITIVES`. L'admin accorde ensuite son grant (+ scopes) comme
pour tout backend.
"""
from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db.mcp import get_backend, insert_backend
from ..db.mcp_catalog import prune_absent, upsert_primitive
from ..db.tables import users
from .devpod_tools.registry import DEVPOD_PRIMITIVES, definition_hash

log = structlog.get_logger(__name__)

DEVPOD_NAMESPACE = "devpod"
_SYSTEM_LOGIN = "__system__"


def backend_id_for(login: str) -> str:
    return f"devpod-{login}"


async def ensure_devpod_backend(conn: AsyncConnection, login: str) -> None:
    """Crée (si absent) le backend devpod du user et synchronise son catalogue."""
    bid = backend_id_for(login)
    if await get_backend(conn, login, bid) is None:
        await insert_backend(
            conn,
            id=bid,
            owner_login=login,
            namespace=DEVPOD_NAMESPACE,
            name="DevPod workspaces",
            url="",
            transport="internal",
        )
    for original_name, defn in DEVPOD_PRIMITIVES.items():
        await upsert_primitive(
            conn,
            backend_id=bid,
            kind="tool",
            original_name=original_name,
            definition=defn,
            definition_hash=definition_hash(defn),
        )
    await prune_absent(conn, bid, "tool", list(DEVPOD_PRIMITIVES))


async def bootstrap_devpod(conn: AsyncConnection) -> None:
    """Enregistre le backend devpod pour tous les users réels (≠ __system__)."""
    rows = await conn.execute(select(users.c.login).where(users.c.login != _SYSTEM_LOGIN))
    logins = [r[0] for r in rows.all()]
    for login in logins:
        await ensure_devpod_backend(conn, login)
    log.info("devpod_bootstrap_done", users=len(logins), primitives=len(DEVPOD_PRIMITIVES))
