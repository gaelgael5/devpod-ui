from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

import structlog
from mcp import ClientSession
from mcp.types import CallToolResult, GetPromptResult, ReadResourceResult, ServerCapabilities
from pydantic import AnyUrl

logger = structlog.get_logger(__name__)

_CAP_KINDS: tuple[tuple[str, str], ...] = (
    ("tool", "tools"),
    ("resource", "resources"),
    ("prompt", "prompts"),
)


def advertised_kinds(caps: ServerCapabilities | None) -> tuple[str, ...]:
    """Kinds de primitives annoncés par les capabilities du serveur."""
    if caps is None:
        return ()
    return tuple(kind for kind, attr in _CAP_KINDS if getattr(caps, attr) is not None)


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
    kinds = advertised_kinds(caps)
    out: list[dict[str, Any]] = []

    if "tool" in kinds:
        tools_result = await session.list_tools()
        for tool in tools_result.tools:
            d = tool.model_dump(mode="json", exclude_none=True)
            out.append(_entry("tool", tool.name, d))
        logger.debug("mcp.client.fetch_primitives.tools", count=len(tools_result.tools))

    if "resource" in kinds:
        resources_result = await session.list_resources()
        for resource in resources_result.resources:
            d = resource.model_dump(mode="json", exclude_none=True)
            out.append(_entry("resource", str(resource.uri), d))
        logger.debug("mcp.client.fetch_primitives.resources", count=len(resources_result.resources))

    if "prompt" in kinds:
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
    read_timeout_seconds: timedelta | None = None,
) -> CallToolResult:
    """Appelle un outil MCP sur la session donnée et retourne le résultat brut.

    read_timeout_seconds plafonne la lecture de la réponse de CET appel
    (les tools longs streament en SSE) — None laisse le défaut du transport.
    """
    return await session.call_tool(name, arguments, read_timeout_seconds=read_timeout_seconds)


async def read_backend_resource(session: ClientSession, uri: AnyUrl) -> ReadResourceResult:
    """Lit une ressource d'un backend ; retourne le résultat brut non transformé."""
    return await session.read_resource(uri)


async def get_backend_prompt(
    session: ClientSession, name: str, arguments: dict[str, str] | None = None
) -> GetPromptResult:
    """Récupère un prompt d'un backend ; retourne le résultat brut non transformé."""
    return await session.get_prompt(name, arguments)
