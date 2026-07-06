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
    PrimitiveQuarantined,
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
        description=(
            "Liste les backends MCP fédérés configurés par l'utilisateur et leur disponibilité. "
            "Retourne : id, namespace, name, url, transport, app_url, enabled, health. "
            "health = dernier monitoring périodique ; 'unknown' si jamais sondé. "
            "Impact: read-only — aucune mutation."
        ),
        inputSchema={"type": "object", "additionalProperties": False, "properties": {}},
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
    per_namespace: dict[str, int] = {}
    for p in prims:
        per_namespace[p.namespace] = per_namespace.get(p.namespace, 0) + 1
    # Trace du tools/list réellement servi au connecteur : permet de trancher
    # « l'outil manque côté passerelle » vs « le connecteur a une liste périmée ».
    log.info(
        "mcp_tools_list_served",
        apikey_id=apikey_id,
        owner=owner_login,
        total=len(tools),
        per_namespace=per_namespace,
    )
    return tools


async def _gateway_list_backends(
    conn: AsyncConnection, owner_login: str
) -> types.CallToolResult:
    """Retourne la liste des backends MCP de l'owner sous forme de CallToolResult JSON."""
    backends = await list_backends(conn, owner_login)
    payload = [
        {
            "id": b["id"],
            "namespace": b["namespace"],
            "name": b["name"],
            "url": b.get("url"),
            "transport": b.get("transport"),
            "app_url": b.get("app_url"),
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
    Chaque appel est tracé à la réception puis à la décision — si un appel
    n'apparaît pas dans `mcp_tool_call_received`, il n'a jamais atteint la
    passerelle (blocage en amont, côté client/connecteur).
    """
    log.info(
        "mcp_tool_call_received", tool=name, apikey_id=apikey_id, owner=owner_login
    )
    session_fn = open_session_fn if open_session_fn is not None else open_session
    if name == GATEWAY_LIST_BACKENDS:
        result = await _gateway_list_backends(conn, owner_login)
        await audit_record(
            conn, apikey_id=apikey_id, owner_login=owner_login,
            namespaced_name=name, backend_id=None, backend_key_id=None,
            latency_ms=None, status="ok", error=None,
        )
        log.info(
            "mcp_tool_call_decision", tool=name, apikey_id=apikey_id,
            decision="dispatched", backend_id=None, reason="outil natif gateway",
        )
        return result

    try:
        target = await resolve_call(
            conn, apikey_id=apikey_id, owner_login=owner_login, namespaced_name=name, kind="tool"
        )
    except PrimitiveQuarantined as exc:
        await audit_record(
            conn, apikey_id=apikey_id, owner_login=owner_login,
            namespaced_name=name, backend_id=exc.backend_id, backend_key_id=None,
            latency_ms=None, status="denied", error="quarantined",
        )
        log.warning(
            "mcp_tool_call_decision", tool=name, apikey_id=apikey_id,
            decision="quarantined", backend_id=exc.backend_id,
            reason="redéfinition détectée, en attente d'approbation",
        )
        raise McpError(
            ErrorData(
                code=METHOD_NOT_FOUND,
                message="tool indisponible (en attente d'approbation)",
            )
        ) from exc
    if target is None:
        await audit_record(
            conn, apikey_id=apikey_id, owner_login=owner_login,
            namespaced_name=name, backend_id=None, backend_key_id=None,
            latency_ms=None, status="denied", error=None,
        )
        log.warning(
            "mcp_tool_call_decision", tool=name, apikey_id=apikey_id,
            decision="unknown_tool", backend_id=None,
            reason="absent du catalogue ou non autorisé par le profil (deny-by-default)",
        )
        raise McpError(ErrorData(code=METHOD_NOT_FOUND, message="unknown tool"))

    log.info(
        "mcp_tool_call_decision", tool=name, apikey_id=apikey_id,
        decision="dispatched", backend_id=target.backend_id, reason=None,
    )
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
            async with session_fn(target.url, transport=target.transport, bearer=bearer) as session:
                result = await call_backend_tool(session, target.original_name, arguments)
    except BackendUnavailable as exc:
        await audit_record(
            conn, apikey_id=apikey_id, owner_login=owner_login,
            namespaced_name=name, backend_id=target.backend_id,
            backend_key_id=target.backend_key_id, latency_ms=None,
            status="timeout", error=str(exc),
        )
        log.warning(
            "mcp_tool_call_backend_unavailable", tool=name, apikey_id=apikey_id,
            backend_id=target.backend_id, reason=str(exc),
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
    try:
        target = await resolve_call(
            conn, apikey_id=apikey_id, owner_login=owner_login, namespaced_name=name, kind="prompt"
        )
    except PrimitiveQuarantined as exc:
        await audit_record(
            conn, apikey_id=apikey_id, owner_login=owner_login,
            namespaced_name=name, backend_id=exc.backend_id, backend_key_id=None,
            latency_ms=None, status="denied", error="quarantined",
        )
        raise McpError(
            ErrorData(
                code=METHOD_NOT_FOUND,
                message="prompt indisponible (en attente d'approbation)",
            )
        ) from exc
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
        async with session_fn(target.url, transport=target.transport, bearer=bearer) as session:
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
