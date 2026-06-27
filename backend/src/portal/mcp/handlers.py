from __future__ import annotations

import json
import time
from typing import Any

import structlog
from mcp import types
from mcp.shared.exceptions import McpError
from mcp.types import (
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    ErrorData,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import list_backends
from portal.db.mcp_audit import record as audit_record
from portal.mcp.aggregator import (
    aggregate_primitives,
    resolve_call,
)
from portal.mcp.client import call_backend_tool, get_backend_prompt
from portal.mcp.connections import BackendUnavailable, open_session
from portal.mcp.devpod_tools import execute_internal_tool
from portal.mcp.dispatch_common import resolve_bearer
from portal.mcp.monitor import get_health

log = structlog.get_logger(__name__)

GATEWAY_LIST_BACKENDS = "gateway__list_backends"


# Computed once at module load — no per-call allocation.
_NATIVE_TOOLS: list[types.Tool] = [
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
    tools.extend(_NATIVE_TOOLS)
    return tools


async def _gateway_list_backends(
    conn: AsyncConnection, owner_login: str
) -> types.CallToolResult:
    """Retourne la liste des backends MCP de l'owner sous forme de CallToolResult JSON."""
    backends = await list_backends(conn, owner_login)
    payload = [
        {
            "namespace": b["namespace"],
            "name": b["name"],
            "enabled": b["enabled"],
            "health": get_health(b["id"]).status,
        }
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
    open_session_fn: Any | None = None,
) -> types.CallToolResult:
    """Route un tools/call namespacé vers son backend.

    Deny-by-default + mapping erreurs §13 + audit à chaque sortie.
    """
    session_fn = open_session_fn if open_session_fn is not None else open_session
    if name == GATEWAY_LIST_BACKENDS:
        result = await _gateway_list_backends(conn, owner_login)
        await audit_record(
            conn, apikey_id=apikey_id, owner_login=owner_login,
            namespaced_name=name, backend_id=None, backend_key_id=None,
            latency_ms=None, status="ok", error=None,
        )
        return result

    target = await resolve_call(
        conn, apikey_id=apikey_id, owner_login=owner_login, namespaced_name=name, kind="tool"
    )
    if target is None:
        await audit_record(
            conn, apikey_id=apikey_id, owner_login=owner_login,
            namespaced_name=name, backend_id=None, backend_key_id=None,
            latency_ms=None, status="denied", error=None,
        )
        raise McpError(ErrorData(code=METHOD_NOT_FOUND, message="unknown tool"))

    bearer = await resolve_bearer(
        conn, target, name=name, apikey_id=apikey_id, owner_login=owner_login
    )

    started = time.perf_counter()
    try:
        if target.transport == "internal":
            # Backend interne (devpod) : implémentation Python locale, pas d'appel HTTP.
            result = await execute_internal_tool(
                conn, target.original_name, arguments, owner_login=owner_login
            )
        else:
            async with session_fn(target.url, bearer=bearer) as session:
                result = await call_backend_tool(session, target.original_name, arguments)
    except BackendUnavailable as exc:
        await audit_record(
            conn, apikey_id=apikey_id, owner_login=owner_login,
            namespaced_name=name, backend_id=target.backend_id,
            backend_key_id=target.backend_key_id, latency_ms=None,
            status="timeout", error=str(exc),
        )
        raise McpError(
            ErrorData(code=INTERNAL_ERROR, message=f"backend unavailable: {target.backend_id}")
        ) from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    await audit_record(
        conn, apikey_id=apikey_id, owner_login=owner_login,
        namespaced_name=name, backend_id=target.backend_id,
        backend_key_id=target.backend_key_id, latency_ms=latency_ms,
        status="error" if result.isError else "ok",
        error=None,
    )
    return result


async def build_prompt_descriptors(
    conn: AsyncConnection, *, apikey_id: str, owner_login: str
) -> list[types.Prompt]:
    """Prompts autorisés (namespacés) pour cette apikey."""
    prims = await aggregate_primitives(
        conn, apikey_id=apikey_id, owner_login=owner_login, kind="prompt"
    )
    return [
        types.Prompt(
            name=p.namespaced_name,
            description=p.definition.get("description"),
            arguments=p.definition.get("arguments"),
        )
        for p in prims
    ]


async def execute_prompt_get(
    conn: AsyncConnection,
    *,
    apikey_id: str,
    owner_login: str,
    name: str,
    arguments: dict[str, str] | None,
    open_session_fn: Any | None = None,
) -> types.GetPromptResult:
    """Route un prompts/get namespacé vers son backend. Deny-by-default + audit à chaque sortie."""
    session_fn = open_session_fn if open_session_fn is not None else open_session
    target = await resolve_call(
        conn, apikey_id=apikey_id, owner_login=owner_login, namespaced_name=name, kind="prompt"
    )
    if target is None:
        await audit_record(
            conn, apikey_id=apikey_id, owner_login=owner_login,
            namespaced_name=name, backend_id=None, backend_key_id=None,
            latency_ms=None, status="denied", error=None,
        )
        raise McpError(ErrorData(code=METHOD_NOT_FOUND, message="unknown prompt"))

    bearer = await resolve_bearer(
        conn, target, name=name, apikey_id=apikey_id, owner_login=owner_login
    )

    started = time.perf_counter()
    try:
        async with session_fn(target.url, bearer=bearer) as session:
            result = await get_backend_prompt(session, target.original_name, arguments)
    except BackendUnavailable as exc:
        await audit_record(
            conn, apikey_id=apikey_id, owner_login=owner_login,
            namespaced_name=name, backend_id=target.backend_id,
            backend_key_id=target.backend_key_id, latency_ms=None,
            status="timeout", error=str(exc),
        )
        raise McpError(
            ErrorData(code=INTERNAL_ERROR, message=f"backend unavailable: {target.backend_id}")
        ) from exc

    await audit_record(
        conn, apikey_id=apikey_id, owner_login=owner_login,
        namespaced_name=name, backend_id=target.backend_id,
        backend_key_id=target.backend_key_id,
        latency_ms=int((time.perf_counter() - started) * 1000),
        status="ok", error=None,
    )
    return result
