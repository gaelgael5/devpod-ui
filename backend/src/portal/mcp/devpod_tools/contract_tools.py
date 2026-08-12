"""Primitives MCP de lecture des contrats OpenAPI (scope admin).

`openapi_contract_list` : nom + URL de chaque contrat enregistré.
`openapi_contract_get` : paramétrage complet d'un contrat (métadonnées + serveurs
+ opérations appelables), par id ou par label.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from ...automations import contracts as ct
from ...db import openapi_contract as oc
from .errors import DevpodToolError


def _summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "label": row["label"],
        "url": row.get("source_url"),
        "category": row.get("category", ""),
        "version": row.get("version", ""),
    }


async def _contract_list(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    return [_summary(r) for r in await oc.list_all(conn)]


async def _by_id_or_label(conn: AsyncConnection, needle: str) -> dict[str, Any] | None:
    row = await oc.get(conn, needle)
    if row is not None:
        return row
    for candidate in await oc.list_all(conn):
        if candidate["label"] == needle:
            return candidate
    return None


async def _contract_get(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    needle = str(args.get("contract") or "").strip()
    if not needle:
        raise DevpodToolError("contract requis (id ou label)")
    row = await _by_id_or_label(conn, needle)
    if row is None:
        raise DevpodToolError(f"contrat introuvable : {needle!r}")
    spec = row["raw_spec"]
    return {
        **_summary(row),
        "servers": ct.servers(spec),
        "operations": ct.list_operations(spec),
    }


CONTRACT_IMPLS = {
    "openapi_contract_list": _contract_list,
    "openapi_contract_get": _contract_get,
}
