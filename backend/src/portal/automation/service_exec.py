"""Exécution d'un outil MCP au nom d'un utilisateur, via un service enregistré.

Le service (user_services) porte un profil MCP ; le profil autorise des outils
namespacés sur des backends. La résolution passe par l'agrégateur (mêmes règles
que la gateway : backends enabled, filtrage tools, quarantaine, clé sortante
explicite ou auto-résolue). La connexion DB est refermée AVANT l'appel réseau.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from mcp.types import CallToolResult, TextContent

from ..db.engine import _get_engine
from ..db.mcp import get_backend_key_secret
from ..db.user_services import get_service
from ..mcp.aggregator import (
    AggregatedPrimitive,
    PrimitiveQuarantined,
    aggregate_primitives_for_profile,
    resolve_call_for_profile,
)
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


async def list_service_tools(
    conn: Any, owner_login: str, service_id: str
) -> list[AggregatedPrimitive]:
    """Outils MCP qu'un service met à disposition (via son profil)."""
    service = await get_service(conn, owner_login, service_id)
    if service is None:
        raise AutomationError(f"service introuvable: {service_id!r}")
    profile_id = service["mcp_profile_id"]
    if not profile_id:
        return []
    return await aggregate_primitives_for_profile(
        conn, profile_id=profile_id, owner_login=owner_login, kind="tool"
    )


async def call_service_primitive(
    owner_login: str, service_id: str, tool: str, args: dict[str, Any]
) -> Any:
    """Appelle `tool` (nom namespacé) autorisé par le profil du service."""
    async with _get_engine().connect() as conn:
        service = await get_service(conn, owner_login, service_id)
        if service is None:
            raise AutomationError(f"service introuvable: {service_id!r}")
        profile_id = service["mcp_profile_id"]
        if not profile_id:
            raise AutomationError(f"service {service['name']!r}: aucun profil MCP associé")
        try:
            target = await resolve_call_for_profile(
                conn,
                profile_id=profile_id,
                owner_login=owner_login,
                namespaced_name=tool,
                kind="tool",
            )
        except PrimitiveQuarantined as exc:
            raise AutomationError(
                f"outil {tool!r} indisponible (en attente d'approbation)"
            ) from exc
        if target is None:
            raise AutomationError(
                f"outil {tool!r} non autorisé par le profil du service {service['name']!r}"
            )
        bearer: str | None = None
        if target.transport != "internal" and target.backend_key_id:
            key_row = await get_backend_key_secret(conn, target.backend_id, target.backend_key_id)
            secret = await resolve_grant_key(key_row)
            bearer = secret.reveal() if secret is not None else None

    _log.info(
        "automation_service_call",
        owner=owner_login,
        service_id=service_id,
        tool=tool,
        transport=target.transport,
    )
    if target.transport == "internal":
        from ..mcp.devpod_tools import execute_internal_tool

        async with _get_engine().begin() as tool_conn:
            result = await execute_internal_tool(
                tool_conn, target.original_name, args, owner_login=owner_login
            )
    else:
        async with open_session(target.url, transport=target.transport, bearer=bearer) as session:
            result = await call_backend_tool(session, target.original_name, args)
    return _result_payload(result)
