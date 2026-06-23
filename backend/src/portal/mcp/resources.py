from __future__ import annotations

import base64
import time
from typing import Any

import structlog
from mcp import types
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.shared.exceptions import McpError
from mcp.types import (
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    ErrorData,
    ReadResourceResult,
)
from pydantic import AnyUrl, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp_audit import record as audit_record
from portal.mcp.aggregator import (
    aggregate_primitives,
    make_namespaced_uri,
    resolve_resource,
)
from portal.mcp.client import read_backend_resource
from portal.mcp.connections import BackendUnavailable, open_session
from portal.mcp.dispatch_common import resolve_bearer

log = structlog.get_logger(__name__)

_ANYURL: TypeAdapter[AnyUrl] = TypeAdapter(AnyUrl)


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
        else:
            log.warning("mcp_unknown_resource_content_type", type=type(c).__name__)
    return out


async def execute_resource_read(
    conn: AsyncConnection,
    *,
    apikey_id: str,
    owner_login: str,
    namespaced_uri: str,
    open_session_fn: Any | None = None,
) -> list[ReadResourceContents]:
    """Route un resources/read vers son backend. Deny-by-default + audit à chaque sortie."""
    session_fn = open_session_fn if open_session_fn is not None else open_session
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

    bearer = await resolve_bearer(
        conn, target, name=namespaced_uri, apikey_id=apikey_id, owner_login=owner_login
    )

    started = time.perf_counter()
    try:
        async with session_fn(target.url, bearer=bearer) as session:
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
