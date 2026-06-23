from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from mcp import types
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, METHOD_NOT_FOUND, ErrorData
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import find_apikey_by_hash, get_backend_key_secret, list_backends
from portal.mcp.aggregator import aggregate_primitives, resolve_call
from portal.mcp.client import call_backend_tool
from portal.mcp.connections import BackendUnavailable, open_session
from portal.mcp.runtime_secrets import UnresolvableSecret, resolve_grant_key
from portal.mcp.service import token_hash

_BEARER_PREFIX = "bearer "

GATEWAY_LIST_BACKENDS = "gateway__list_backends"


def _native_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name=GATEWAY_LIST_BACKENDS,
            description="Liste les backends MCP fédérés accessibles et leur disponibilité.",
            inputSchema={"type": "object", "properties": {}},
        )
    ]


def _to_tool(definition: dict[str, Any], namespaced_name: str) -> types.Tool:
    return types.Tool(
        name=namespaced_name,
        description=definition.get("description"),
        inputSchema=definition.get("inputSchema") or {"type": "object"},
    )


async def build_tool_descriptors(
    conn: AsyncConnection, *, apikey_id: str, owner_login: str
) -> list[types.Tool]:
    """Tools autorisés (namespacés) pour cette apikey + tools natifs gateway."""
    prims = await aggregate_primitives(
        conn, apikey_id=apikey_id, owner_login=owner_login, kind="tool"
    )
    tools = [_to_tool(p.definition, p.namespaced_name) for p in prims]
    tools.extend(_native_tools())
    return tools


def extract_bearer(headers: Mapping[str, str]) -> str | None:
    """Extrait le token Bearer de l'en-tête Authorization (schéma insensible à la casse)."""
    raw = headers.get("authorization")
    if not raw or not raw.lower().startswith(_BEARER_PREFIX):
        return None
    token = raw[len(_BEARER_PREFIX) :].strip()
    return token or None


async def resolve_tenant(conn: AsyncConnection, token: str | None) -> dict[str, object] | None:
    """Résout le token apikey clair en ligne apikey (non révoquée) ou None."""
    if not token:
        return None
    return await find_apikey_by_hash(conn, token_hash(token))


async def _gateway_list_backends(
    conn: AsyncConnection, owner_login: str
) -> types.CallToolResult:
    """Retourne la liste des backends MCP de l'owner sous forme de CallToolResult JSON."""
    backends = await list_backends(conn, owner_login)
    payload = [
        {"namespace": b["namespace"], "name": b["name"], "enabled": b["enabled"]}
        for b in backends
    ]
    text = json.dumps(payload)
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)])


async def execute_tool_call(
    conn: AsyncConnection,
    *,
    apikey_id: str,
    owner_login: str,
    name: str,
    arguments: dict[str, Any],
    open_session_fn: Any = open_session,
) -> types.CallToolResult:
    """Route un tools/call namespacé vers son backend (deny-by-default + mapping erreurs).

    Outil natif → gateway locale. Sinon resolve_call ; None → METHOD_NOT_FOUND.
    Résout la clé sortante ; UnresolvableSecret → INTERNAL_ERROR.
    Ouvre la session via open_session_fn (injectable pour les tests) ;
    BackendUnavailable → INTERNAL_ERROR. Forward via call_backend_tool.
    L'audit est ajouté en Task 4 — aucune trace d'audit ici.
    """
    if name == GATEWAY_LIST_BACKENDS:
        return await _gateway_list_backends(conn, owner_login)

    target = await resolve_call(
        conn, apikey_id=apikey_id, owner_login=owner_login, namespaced_name=name, kind="tool"
    )
    if target is None:
        raise McpError(ErrorData(code=METHOD_NOT_FOUND, message=f"tool not found: {name}"))

    key_row = (
        await get_backend_key_secret(conn, target.backend_id, target.backend_key_id)
        if target.backend_key_id
        else None
    )
    try:
        secret = await resolve_grant_key(key_row)
    except UnresolvableSecret as exc:
        raise McpError(
            ErrorData(code=INTERNAL_ERROR, message="outbound key not resolvable at runtime")
        ) from exc
    bearer = secret.reveal() if secret else None

    try:
        async with open_session_fn(target.url, bearer=bearer) as session:
            return await call_backend_tool(session, target.original_name, arguments)
    except BackendUnavailable as exc:
        raise McpError(
            ErrorData(code=INTERNAL_ERROR, message=f"backend unavailable: {target.backend_id}")
        ) from exc
