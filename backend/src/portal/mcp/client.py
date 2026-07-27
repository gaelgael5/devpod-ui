from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
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


# Mots-clés JSON Schema dont la valeur liste est un ENSEMBLE : l'ordre n'a aucune
# signification. On les trie avant de hasher pour qu'un serveur qui les renvoie dans
# un ordre instable ne re-quarantine pas un outil inchangé (spec 23). Tout autre
# tableau (default, examples, prefixItems…) garde son ordre : il peut porter du sens,
# et l'aplatir affaiblirait la détection de redéfinition.
_SET_ARRAY_KEYS = frozenset({"required", "enum", "type"})


def _canonicalize(node: Any, *, parent_key: str | None = None) -> Any:
    """Copie normalisée d'une définition : trie les tableaux-ensembles, récursivement."""
    if isinstance(node, dict):
        return {k: _canonicalize(v, parent_key=k) for k, v in node.items()}
    if isinstance(node, list):
        items = [_canonicalize(v) for v in node]
        if parent_key in _SET_ARRAY_KEYS:
            # Clé de tri = JSON canonique de l'élément → déterministe même pour des
            # types mixtes (str/int/bool/None) ou des éléments imbriqués.
            return sorted(
                items,
                key=lambda e: json.dumps(e, sort_keys=True, ensure_ascii=False),
            )
        return items
    return node


def hash_definition(definition: dict[str, Any]) -> str:
    """Calcule le sha256 du JSON canonique d'une définition de primitive MCP.

    Canonicalisation : ordre des clés d'objet neutralisé (sort_keys) ET ordre des
    tableaux-ensembles (`required`/`enum`/`type`) neutralisé — sinon un serveur qui
    les renvoie dans un ordre variable re-quarantine des outils pourtant identiques.
    """
    canonical = json.dumps(
        _canonicalize(definition), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _entry(kind: str, original_name: str, definition: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": kind,
        "original_name": original_name,
        "definition": definition,
        "definition_hash": hash_definition(definition),
    }


async def _paginate(
    list_page: Callable[[str | None], Awaitable[Any]],
    items_attr: str,
) -> list[Any]:
    """Suit `nextCursor` jusqu'à épuisement et concatène les éléments de chaque page.

    Un backend MCP conforme pagine `list_tools`/`list_resources`/`list_prompts` :
    ne lire que la première page (le comportement historique) perd toute la queue
    du catalogue, que `prune_absent` efface ensuite — c'est le bug du registre
    fédéré partiel (docflow create_document / set_document_parent).

    Garde-fou anti-boucle : un curseur déjà vu (serveur qui ne progresse pas)
    arrête l'itération plutôt que de boucler indéfiniment.
    """
    items: list[Any] = []
    cursor: str | None = None
    seen: set[str] = set()
    while True:
        result = await list_page(cursor)
        items.extend(getattr(result, items_attr))
        cursor = result.nextCursor
        if cursor is None or cursor in seen:
            break
        seen.add(cursor)
    return items


async def fetch_primitives(session: ClientSession) -> list[dict[str, Any]]:
    """Énumère les primitives d'un backend MCP, normalisées pour le catalogue.

    N'interroge que les familles annoncées dans les capabilities du serveur
    (un backend tools-only ne supporte pas resources/prompts). Chaque famille est
    paginée (`nextCursor`) : aucune primitive au-delà de la première page n'est
    perdue.
    """
    caps = session.get_server_capabilities()
    kinds = advertised_kinds(caps)
    out: list[dict[str, Any]] = []

    if "tool" in kinds:
        logger.debug("mcp.client.fetch_primitives.tools.start")
        tools = await _paginate(lambda c: session.list_tools(c), "tools")
        for tool in tools:
            d = tool.model_dump(mode="json", exclude_none=True)
            out.append(_entry("tool", tool.name, d))
        logger.debug("mcp.client.fetch_primitives.tools", count=len(tools))

    if "resource" in kinds:
        logger.debug("mcp.client.fetch_primitives.resources.start")
        resources = await _paginate(lambda c: session.list_resources(c), "resources")
        for resource in resources:
            d = resource.model_dump(mode="json", exclude_none=True)
            out.append(_entry("resource", str(resource.uri), d))
        logger.debug("mcp.client.fetch_primitives.resources", count=len(resources))

    if "prompt" in kinds:
        logger.debug("mcp.client.fetch_primitives.prompts.start")
        prompts = await _paginate(lambda c: session.list_prompts(c), "prompts")
        for prompt in prompts:
            d = prompt.model_dump(mode="json", exclude_none=True)
            out.append(_entry("prompt", prompt.name, d))
        logger.debug("mcp.client.fetch_primitives.prompts", count=len(prompts))

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
