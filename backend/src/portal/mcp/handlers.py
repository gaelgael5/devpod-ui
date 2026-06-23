from __future__ import annotations

import base64
import json
import time
from collections.abc import Mapping
from typing import Any

import structlog
from mcp import types
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.shared.exceptions import McpError
from mcp.types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    ErrorData,
    ReadResourceResult,
)
from pydantic import AnyUrl, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import find_apikey_by_hash, get_backend_key_secret, list_backends
from portal.db.mcp_audit import record as audit_record
from portal.mcp.aggregator import (
    CallTarget,
    aggregate_primitives,
    make_namespaced_uri,
    resolve_call,
    resolve_resource,
)
from portal.mcp.client import call_backend_tool, get_backend_prompt, read_backend_resource
from portal.mcp.connections import BackendUnavailable, open_session
from portal.mcp.runtime_secrets import UnresolvableSecret, resolve_grant_key
from portal.mcp.service import token_hash

log = structlog.get_logger(__name__)

_BEARER_PREFIX = "bearer "
_ANYURL: TypeAdapter[AnyUrl] = TypeAdapter(AnyUrl)
_UNAUTHORIZED = ErrorData(code=INVALID_PARAMS, message="missing or invalid API key")

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


async def _resolve_bearer(
    conn: AsyncConnection,
    target: CallTarget,
    *,
    name: str,
    apikey_id: str,
    owner_login: str,
) -> str | None:
    """Résout la clé sortante en bearer HTTP (None si pas de clé).

    Audit 'error' + McpError(INTERNAL_ERROR) si non résolvable.
    """
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
    return secret.reveal() if secret else None


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

    bearer = await _resolve_bearer(
        conn, target, name=name, apikey_id=apikey_id, owner_login=owner_login
    )

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
    open_session_fn: Any = open_session,
) -> types.GetPromptResult:
    """Route un prompts/get namespacé vers son backend. Deny-by-default + audit à chaque sortie."""
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

    bearer = await _resolve_bearer(
        conn, target, name=name, apikey_id=apikey_id, owner_login=owner_login
    )

    started = time.perf_counter()
    try:
        async with open_session_fn(target.url, bearer=bearer) as session:
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


async def build_resource_descriptors(
    conn: AsyncConnection, *, apikey_id: str, owner_login: str
) -> list[types.Resource]:
    """Resources autorisées (URIs namespacées) pour cette apikey."""
    prims = await aggregate_primitives(
        conn, apikey_id=apikey_id, owner_login=owner_login, kind="resource"
    )
    return [
        types.Resource(
            uri=_ANYURL.validate_python(make_namespaced_uri(p.namespace, p.original_name)),
            name=p.definition.get("name") or p.original_name,
            description=p.definition.get("description"),
            mimeType=p.definition.get("mimeType"),
        )
        for p in prims
    ]


def _to_read_contents(result: ReadResourceResult) -> list[ReadResourceContents]:
    """Convertit un ReadResourceResult SDK en liste de ReadResourceContents.

    Note SDK : le handler read_resource bas-niveau assigne l'URI de la requête
    (namespacée) aux contents renvoyés — les URIs internes par-content du backend
    ne sont donc pas préservées dans le résultat final.
    """
    out: list[ReadResourceContents] = []
    for c in result.contents:
        if isinstance(c, types.TextResourceContents):
            out.append(ReadResourceContents(content=c.text, mime_type=c.mimeType))
        elif isinstance(c, types.BlobResourceContents):
            out.append(ReadResourceContents(content=base64.b64decode(c.blob), mime_type=c.mimeType))
    return out


async def execute_resource_read(
    conn: AsyncConnection,
    *,
    apikey_id: str,
    owner_login: str,
    namespaced_uri: str,
    open_session_fn: Any = open_session,
) -> list[ReadResourceContents]:
    """Route un resources/read vers son backend. Deny-by-default + audit à chaque sortie."""
    target = await resolve_resource(
        conn, apikey_id=apikey_id, owner_login=owner_login, namespaced_uri=namespaced_uri
    )
    if target is None:
        await audit_record(
            conn, apikey_id=apikey_id, owner_login=owner_login,
            namespaced_name=namespaced_uri, backend_id=None, backend_key_id=None,
            latency_ms=None, status="denied", error=None,
        )
        raise McpError(ErrorData(code=METHOD_NOT_FOUND, message="unknown resource"))

    bearer = await _resolve_bearer(
        conn, target, name=namespaced_uri, apikey_id=apikey_id, owner_login=owner_login
    )

    started = time.perf_counter()
    try:
        async with open_session_fn(target.url, bearer=bearer) as session:
            original_uri = _ANYURL.validate_python(target.original_name)
            result = await read_backend_resource(session, original_uri)
    except BackendUnavailable as exc:
        await audit_record(
            conn, apikey_id=apikey_id, owner_login=owner_login,
            namespaced_name=namespaced_uri, backend_id=target.backend_id,
            backend_key_id=target.backend_key_id, latency_ms=None,
            status="timeout", error=str(exc),
        )
        raise McpError(
            ErrorData(code=INTERNAL_ERROR, message=f"backend unavailable: {target.backend_id}")
        ) from exc

    await audit_record(
        conn, apikey_id=apikey_id, owner_login=owner_login,
        namespaced_name=namespaced_uri, backend_id=target.backend_id,
        backend_key_id=target.backend_key_id,
        latency_ms=int((time.perf_counter() - started) * 1000),
        status="ok", error=None,
    )
    return _to_read_contents(result)
