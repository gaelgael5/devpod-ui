from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

import structlog
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS, METHOD_NOT_FOUND, ErrorData
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.engine import _get_engine
from portal.db.mcp import find_apikey_by_hash, get_backend_key_secret, list_backends
from portal.db.mcp_audit import record as audit_record
from portal.mcp.aggregator import aggregate_primitives, resolve_call
from portal.mcp.client import call_backend_tool
from portal.mcp.connections import BackendUnavailable, open_session
from portal.mcp.runtime_secrets import UnresolvableSecret, resolve_grant_key
from portal.mcp.service import token_hash

log = structlog.get_logger(__name__)

_BEARER_PREFIX = "bearer "
_UNAUTHORIZED = ErrorData(code=INVALID_PARAMS, message="missing or invalid API key")

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
    """Route un tools/call namespacé vers son backend.

    Deny-by-default + mapping erreurs §13 + audit à chaque sortie.
    """
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

    key_row = (
        await get_backend_key_secret(conn, target.backend_id, target.backend_key_id)
        if target.backend_key_id
        else None
    )
    try:
        secret = await resolve_grant_key(key_row)
    except UnresolvableSecret as exc:
        await audit_record(
            conn, apikey_id=apikey_id, owner_login=owner_login,
            namespaced_name=name, backend_id=target.backend_id,
            backend_key_id=target.backend_key_id, latency_ms=None,
            status="error", error="key not resolvable",
        )
        raise McpError(
            ErrorData(code=INTERNAL_ERROR, message="outbound key not resolvable at runtime")
        ) from exc
    bearer = secret.reveal() if secret else None

    started = time.perf_counter()
    try:
        async with open_session_fn(target.url, bearer=bearer) as session:
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


def build_server() -> tuple[Server, StreamableHTTPSessionManager]:
    """Construit le serveur MCP frontal bas-niveau + son gestionnaire de sessions."""
    server: Server = Server("workspace-portal-mcp")

    @server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def _list_tools() -> list[types.Tool]:
        req = server.request_context.request
        token = extract_bearer(req.headers if req is not None else {})
        async with _get_engine().begin() as conn:
            tenant = await resolve_tenant(conn, token)
            if tenant is None:
                raise McpError(_UNAUTHORIZED)
            return await build_tool_descriptors(
                conn, apikey_id=str(tenant["id"]), owner_login=str(tenant["owner_login"])
            )

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> types.CallToolResult:
        req = server.request_context.request
        token = extract_bearer(req.headers if req is not None else {})
        async with _get_engine().begin() as conn:
            tenant = await resolve_tenant(conn, token)
            if tenant is None:
                raise McpError(_UNAUTHORIZED)
            return await execute_tool_call(
                conn, apikey_id=str(tenant["id"]), owner_login=str(tenant["owner_login"]),
                name=name, arguments=arguments or {},
            )

    manager = StreamableHTTPSessionManager(app=server, stateless=False)
    return server, manager
