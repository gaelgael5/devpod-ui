"""Appel serveur→backend d'une primitive MCP au nom d'un utilisateur.

Chemin hors gateway (pas d'apikey) utilisé par les écouteurs d'événements :
le backend est résolu par namespace parmi les backends de l'utilisateur, la
clé sortante est auto-résolue (première clé enabled, même convention que les
entrées de profil sans clé explicite). La connexion DB est refermée AVANT
l'appel réseau MCP, qui peut être long.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from mcp.types import CallToolResult, TextContent

from ..db.engine import _get_engine
from ..db.mcp import get_backend_key_secret, list_backend_keys, list_backends
from ..mcp.client import call_backend_tool
from ..mcp.connections import open_session
from ..mcp.runtime_secrets import resolve_grant_key
from .engine import AutomationError

_log = structlog.get_logger(__name__)


def _result_payload(result: CallToolResult) -> Any:
    texts = [c.text for c in result.content if isinstance(c, TextContent)]
    raw = "\n".join(texts)
    if result.isError:
        raise AutomationError(f"outil en erreur: {raw[:500]}")
    try:
        return json.loads(raw)
    except ValueError:
        return raw


async def call_user_primitive(
    owner_login: str, namespace: str, tool: str, args: dict[str, Any]
) -> Any:
    async with _get_engine().connect() as conn:
        backends = await list_backends(conn, owner_login)
        backend = next((b for b in backends if b["namespace"] == namespace and b["enabled"]), None)
        if backend is None:
            raise AutomationError(
                f"backend MCP {namespace!r} introuvable ou désactivé pour {owner_login!r}"
            )
        bearer: str | None = None
        if backend["transport"] != "internal":
            keys = [k for k in await list_backend_keys(conn, backend["id"]) if k["enabled"]]
            key_row = (
                await get_backend_key_secret(conn, backend["id"], keys[0]["id"]) if keys else None
            )
            secret = await resolve_grant_key(key_row)
            bearer = secret.reveal() if secret is not None else None

    _log.info(
        "automation_primitive_call",
        owner=owner_login,
        namespace=namespace,
        tool=tool,
        transport=backend["transport"],
    )
    if backend["transport"] == "internal":
        from ..mcp.devpod_tools import execute_internal_tool

        async with _get_engine().begin() as tool_conn:
            result = await execute_internal_tool(tool_conn, tool, args, owner_login=owner_login)
    else:
        async with open_session(
            backend["url"], transport=backend["transport"], bearer=bearer
        ) as session:
            result = await call_backend_tool(session, tool, args)
    return _result_payload(result)
