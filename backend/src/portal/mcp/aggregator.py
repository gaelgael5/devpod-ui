from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import get_backend, list_grants
from portal.db.mcp_catalog import list_primitives

NS_SEP = "__"


class AggregatedPrimitive(BaseModel):
    """Primitive d'un backend, préfixée et prête à exposer côté frontal."""

    model_config = ConfigDict(frozen=True)

    namespaced_name: str
    kind: str
    backend_id: str
    original_name: str
    definition: dict[str, Any]


def split_namespaced(name: str) -> tuple[str, str] | None:
    """Découpe `<namespace>__<original>` sur le PREMIER `__`.

    Renvoie `None` si aucun `__` ou si le préfixe namespace est vide.
    """
    idx = name.find(NS_SEP)
    if idx <= 0:
        return None
    return name[:idx], name[idx + len(NS_SEP) :]


def _curation_allows(expose_mode: str, expose: list[str], original_name: str) -> bool:
    if expose_mode == "allowlist":
        return original_name in expose
    if expose_mode == "denylist":
        return original_name not in expose
    return True  # "all"


async def aggregate_primitives(
    conn: AsyncConnection, *, apikey_id: str, owner_login: str, kind: str
) -> list[AggregatedPrimitive]:
    """Vue agrégée des primitives `kind` autorisées pour cette apikey.

    grants → backends enabled & possédés → catalogue → curation → namespacing,
    en excluant les primitives quarantined.
    """
    out: list[AggregatedPrimitive] = []
    for grant in await list_grants(conn, apikey_id):
        backend = await get_backend(conn, owner_login, grant["backend_id"])
        if backend is None or not backend["enabled"]:
            continue
        namespace = backend["namespace"]
        expose = grant["expose"] or []
        for prim in await list_primitives(conn, grant["backend_id"], kind):
            if prim["quarantined"]:
                continue
            if not _curation_allows(grant["expose_mode"], expose, prim["original_name"]):
                continue
            out.append(
                AggregatedPrimitive(
                    namespaced_name=f"{namespace}{NS_SEP}{prim['original_name']}",
                    kind=kind,
                    backend_id=grant["backend_id"],
                    original_name=prim["original_name"],
                    definition=prim["definition"],
                )
            )
    return out
