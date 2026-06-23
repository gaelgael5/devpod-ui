from __future__ import annotations

import hashlib
import json
from typing import Any

import structlog
from mcp import ClientSession
from mcp.types import CallToolResult

logger = structlog.get_logger(__name__)


def hash_definition(definition: dict[str, Any]) -> str:
    """Calcule le sha256 du JSON canonique d'une définition de primitive MCP."""
    canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _entry(kind: str, original_name: str, definition: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": kind,
        "original_name": original_name,
        "definition": definition,
        "definition_hash": hash_definition(definition),
    }


async def fetch_primitives(session: ClientSession) -> list[dict[str, Any]]:
    """Énumère les primitives d'un backend MCP, normalisées pour le catalogue.

    N'interroge que les familles annoncées dans les capabilities du serveur
    (un backend tools-only ne supporte pas resources/prompts).
    """
    caps = session.get_server_capabilities()
    out: list[dict[str, Any]] = []
    if caps is None:
        return out

    if caps.tools is not None:
        tools_result = await session.list_tools()
        for tool in tools_result.tools:
            d = tool.model_dump(mode="json", exclude_none=True)
            out.append(_entry("tool", tool.name, d))
        logger.debug("mcp.client.fetch_primitives.tools", count=len(tools_result.tools))

    if caps.resources is not None:
        resources_result = await session.list_resources()
        for resource in resources_result.resources:
            d = resource.model_dump(mode="json", exclude_none=True)
            out.append(_entry("resource", str(resource.uri), d))
        logger.debug("mcp.client.fetch_primitives.resources", count=len(resources_result.resources))

    if caps.prompts is not None:
        prompts_result = await session.list_prompts()
        for prompt in prompts_result.prompts:
            d = prompt.model_dump(mode="json", exclude_none=True)
            out.append(_entry("prompt", prompt.name, d))
        logger.debug("mcp.client.fetch_primitives.prompts", count=len(prompts_result.prompts))

    return out


async def call_backend_tool(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any],
) -> CallToolResult:
    """Appelle un outil MCP sur la session donnée et retourne le résultat brut."""
    return await session.call_tool(name, arguments)
