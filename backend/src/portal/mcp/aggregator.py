from __future__ import annotations

from typing import Any
from urllib.parse import quote, unquote

import structlog
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import get_backend
from portal.db.mcp_catalog import list_primitives
from portal.db.mcp_profiles import find_first_backend_key, list_entries_for_apikey

log = structlog.get_logger(__name__)

NS_SEP = "__"
_URI_PREFIX = "gw+"


class AggregatedPrimitive(BaseModel):
    """Primitive d'un backend, préfixée et prête à exposer côté frontal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    namespaced_name: str
    kind: str
    namespace: str
    backend_id: str
    original_name: str
    definition: dict[str, Any]


class CallTarget(BaseModel):
    """Routage résolu d'un appel namespacé vers son backend + sa clé sortante."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    backend_id: str
    original_name: str
    url: str
    transport: str
    backend_key_id: str | None


def split_namespaced(name: str) -> tuple[str, str] | None:
    """Découpe `<namespace>__<original>` sur le PREMIER `__`.

    Renvoie `None` si aucun `__` ou si le préfixe namespace est vide.
    """
    idx = name.find(NS_SEP)
    if idx <= 0:
        return None
    return name[:idx], name[idx + len(NS_SEP):]


def make_namespaced_uri(namespace: str, original_uri: str) -> str:
    """URI exposée au client frontal : scheme `gw+<ns>`, URI originale percent-encodée."""
    return f"{_URI_PREFIX}{namespace}:///{quote(original_uri, safe='')}"


def split_namespaced_uri(uri: str) -> tuple[str, str] | None:
    """Inverse de make_namespaced_uri. `None` si l'URI n'est pas une URI gateway."""
    scheme, sep, rest = uri.partition(":///")
    if not sep or not scheme.startswith(_URI_PREFIX):
        return None
    namespace = scheme[len(_URI_PREFIX):]
    if not namespace:
        return None
    return namespace, unquote(rest)


def _tools_allow(tools: list[str] | None, original_name: str) -> bool:
    """null = tous les tools, [] = aucun, liste = subset explicite."""
    if tools is None:
        return True
    return original_name in tools


async def _resolve_backend_key_id(
    conn: AsyncConnection, entry: dict[str, Any]
) -> str | None:
    """Clé sortante : explicite dans l'entry, sinon première clé enabled du backend."""
    if entry["backend_key_id"] is not None:
        return str(entry["backend_key_id"])
    row = await find_first_backend_key(conn, entry["backend_id"])
    return str(row["id"]) if row else None


async def aggregate_primitives(
    conn: AsyncConnection, *, apikey_id: str, owner_login: str, kind: str
) -> list[AggregatedPrimitive]:
    """Vue agrégée des primitives `kind` autorisées pour cette apikey via son profil.

    profile_entries → backends enabled → catalogue → filtrage tools → namespacing.
    """
    out: list[AggregatedPrimitive] = []
    entries = await list_entries_for_apikey(conn, apikey_id=apikey_id, owner_login=owner_login)
    for entry in entries:
        backend = await get_backend(conn, owner_login, entry["backend_id"])
        if backend is None or not backend["enabled"]:
            continue
        namespace = backend["namespace"]
        tools: list[str] | None = entry["tools"]
        for prim in await list_primitives(conn, entry["backend_id"], kind):
            if prim["quarantined"]:
                continue
            if not _tools_allow(tools, prim["original_name"]):
                continue
            out.append(
                AggregatedPrimitive(
                    namespaced_name=f"{namespace}{NS_SEP}{prim['original_name']}",
                    kind=kind,
                    namespace=namespace,
                    backend_id=entry["backend_id"],
                    original_name=prim["original_name"],
                    definition=prim["definition"],
                )
            )
    return out


async def _resolve_target(
    conn: AsyncConnection,
    *,
    apikey_id: str,
    owner_login: str,
    namespace: str,
    original: str,
    kind: str,
) -> CallTarget | None:
    """Cœur de résolution post-découpe. `None` = refusé/inconnu (deny-by-default).

    Ne révèle jamais l'existence d'un backend : tout cas non autorisé renvoie `None`.
    """
    entries = await list_entries_for_apikey(conn, apikey_id=apikey_id, owner_login=owner_login)
    log.debug(
        "resolve_target",
        namespace=namespace,
        original=original,
        kind=kind,
        entry_count=len(entries),
        entry_backends=[e["backend_id"] for e in entries],
    )
    if not entries:
        log.warning("resolve_target_no_entries", namespace=namespace, original=original)
    for entry in entries:
        backend = await get_backend(conn, owner_login, entry["backend_id"])
        if backend is None:
            log.debug("resolve_target_backend_missing", backend_id=entry["backend_id"])
            continue
        if not backend["enabled"]:
            log.debug("resolve_target_backend_disabled", backend_id=entry["backend_id"])
            continue
        if backend["namespace"] != namespace:
            log.debug(
                "resolve_target_namespace_mismatch",
                backend_id=entry["backend_id"],
                backend_ns=backend["namespace"],
                want_ns=namespace,
            )
            continue
        if not _tools_allow(entry["tools"], original):
            log.debug(
                "resolve_target_tools_deny",
                backend_id=entry["backend_id"],
                tools_filter=entry["tools"],
                original=original,
            )
            return None
        prims = await list_primitives(conn, entry["backend_id"], kind)
        match = next((p for p in prims if p["original_name"] == original), None)
        if match is None:
            log.debug(
                "resolve_target_tool_not_in_catalog",
                backend_id=entry["backend_id"],
                original=original,
                catalog_size=len(prims),
            )
            return None
        if match["quarantined"]:
            log.warning(
                "resolve_target_quarantined",
                backend_id=entry["backend_id"],
                original=original,
            )
            return None
        backend_key_id = await _resolve_backend_key_id(conn, entry)
        return CallTarget(
            backend_id=entry["backend_id"],
            original_name=original,
            url=backend["url"],
            transport=backend["transport"],
            backend_key_id=backend_key_id,
        )
    return None


async def resolve_call(
    conn: AsyncConnection,
    *,
    apikey_id: str,
    owner_login: str,
    namespaced_name: str,
    kind: str,
) -> CallTarget | None:
    """Résout le routage d'un appel namespacé (`<ns>__<name>`).

    Délègue à `_resolve_target` après découpe. `None` = refusé/inconnu.
    """
    parsed = split_namespaced(namespaced_name)
    if parsed is None:
        return None
    namespace, original = parsed
    return await _resolve_target(
        conn,
        apikey_id=apikey_id,
        owner_login=owner_login,
        namespace=namespace,
        original=original,
        kind=kind,
    )


async def resolve_resource(
    conn: AsyncConnection,
    *,
    apikey_id: str,
    owner_login: str,
    namespaced_uri: str,
    kind: str = "resource",
) -> CallTarget | None:
    """Résout le routage d'une resource via son URI namespacée (`gw+<ns>:///...`).

    `None` si l'URI n'est pas une URI gateway, ou refusée/inconnue.
    """
    parsed = split_namespaced_uri(namespaced_uri)
    if parsed is None:
        return None
    namespace, original = parsed
    return await _resolve_target(
        conn,
        apikey_id=apikey_id,
        owner_login=owner_login,
        namespace=namespace,
        original=original,
        kind=kind,
    )
