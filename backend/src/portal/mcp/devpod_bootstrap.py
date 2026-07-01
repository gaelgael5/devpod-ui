"""Enregistrement idempotent du backend MCP interne `devpod` au démarrage.

Un backend `devpod` par user réel (modèle per-owner existant) : id=`devpod-{login}`,
namespace `devpod`, transport `internal`, url vide. Le catalogue est peuplé depuis
le registre `DEVPOD_PRIMITIVES`. L'admin accorde ensuite son grant (+ scopes) comme
pour tout backend.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from ..config.store import load_global
from ..db.mcp import get_backend, insert_backend
from ..db.mcp_catalog import prune_absent, set_quarantine, upsert_primitive
from ..db.tables import users
from .devpod_tools.registry import DEVPOD_PRIMITIVES, definition_hash

log = structlog.get_logger(__name__)

DEVPOD_NAMESPACE = "devpod"
_SYSTEM_LOGIN = "__system__"


def backend_id_for(login: str) -> str:
    return f"devpod-{login}"


def _active_primitives() -> dict[str, dict[str, Any]]:
    """Retourne les primitives actives selon la config globale.

    logs_query est exclue si logs.enabled=false (spec 31 §2).
    """
    cfg = load_global()
    if cfg.logs.enabled:
        return DEVPOD_PRIMITIVES
    return {k: v for k, v in DEVPOD_PRIMITIVES.items() if k != "logs_query"}


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
    active = _active_primitives()
    for original_name, defn in active.items():
        await upsert_primitive(
            conn,
            backend_id=bid,
            kind="tool",
            original_name=original_name,
            definition=defn,
            definition_hash=definition_hash(defn),
        )
        # Backend interne : on fait confiance à notre propre code.
        # La quarantaine collante (conçue pour les backends externes) est levée
        # inconditionnellement — qu'elle ait été déclenchée maintenant ou lors
        # d'un run précédent.
        await set_quarantine(conn, bid, "tool", original_name, False)
    await prune_absent(conn, bid, "tool", list(active))


async def bootstrap_devpod(conn: AsyncConnection) -> None:
    """Enregistre le backend devpod pour tous les users réels (≠ __system__)."""
    rows = await conn.execute(select(users.c.login).where(users.c.login != _SYSTEM_LOGIN))
    logins = [r[0] for r in rows.all()]
    for login in logins:
        await ensure_devpod_backend(conn, login)
    log.info("devpod_bootstrap_done", users=len(logins), primitives=len(_active_primitives()))
