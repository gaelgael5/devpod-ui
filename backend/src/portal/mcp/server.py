from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mcp import types
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import find_apikey_by_hash
from portal.mcp.aggregator import aggregate_primitives
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
