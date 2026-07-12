"""Configuration admin d'un backend `rest` : déclaration de ses outils.

Un backend REST n'a pas de catalogue MCP à découvrir — l'admin déclare
explicitement ses outils (contrat MCP + mapping REST). Chaque déclaration est
stockée dans mcp_tool_catalog ; le mapping `rest` embarqué n'est jamais servi au
client (cf. handlers._to_tool), il n'est lu qu'au dispatch (rest_adapter).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from ..db.mcp import get_backend
from ..db.mcp_catalog import prune_absent, upsert_primitive
from .client import hash_definition
from .models import RestToolDeclaration
from .service import InvalidReference, NotFound


def build_rest_definition(decl: RestToolDeclaration) -> dict[str, Any]:
    """Définition catalogue d'un outil REST : champs MCP + mapping `rest` embarqué."""
    return {
        "description": decl.description,
        "inputSchema": decl.input_schema,
        "rest": decl.spec.model_dump(),
    }


async def set_rest_tools(
    conn: AsyncConnection,
    owner_login: str,
    backend_id: str,
    tools: list[RestToolDeclaration],
) -> int:
    """Remplace le jeu d'outils d'un backend `rest`. Retourne le nombre d'outils.

    Refuse un backend inexistant (NotFound) ou d'un autre transport
    (InvalidReference). Les redéfinitions suivent la quarantaine du backend
    (protégée sauf `quarantine_disabled`). Les outils absents du jeu sont élagués.
    """
    backend = await get_backend(conn, owner_login, backend_id)
    if backend is None:
        raise NotFound(f"backend introuvable: {backend_id}")
    if backend.get("transport") != "rest":
        raise InvalidReference("outils REST réservés à un backend de transport rest")

    protect = not bool(backend.get("quarantine_disabled", False))
    for decl in tools:
        definition = build_rest_definition(decl)
        await upsert_primitive(
            conn,
            backend_id=backend_id,
            kind="tool",
            original_name=decl.name,
            definition=definition,
            definition_hash=hash_definition(definition),
            protect=protect,
        )
    await prune_absent(conn, backend_id, "tool", [d.name for d in tools])
    return len(tools)
