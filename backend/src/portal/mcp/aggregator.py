from __future__ import annotations

from typing import Any, Literal
from urllib.parse import quote, unquote

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import get_backend, list_grants
from portal.db.mcp_catalog import list_primitives

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
    return name[:idx], name[idx + len(NS_SEP) :]


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


def _curation_allows(
    expose_mode: Literal["all", "allowlist", "denylist"],
    expose: list[str],
    original_name: str,
) -> bool:
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
        if not grant["enabled"]:
            continue  # service temporairement désactivé pour ce client
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
            # Enforcement par scope, cohérent avec resolve_call : on ne liste que
            # ce qui est réellement appelable (NULL côté grant = pas d'enforcement).
            required_scope = (prim["definition"] or {}).get("scope")
            grant_scopes = grant.get("scopes")
            if (
                required_scope
                and grant_scopes is not None
                and required_scope not in grant_scopes
            ):
                continue
            out.append(
                AggregatedPrimitive(
                    namespaced_name=f"{namespace}{NS_SEP}{prim['original_name']}",
                    kind=kind,
                    namespace=namespace,
                    backend_id=grant["backend_id"],
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
    for grant in await list_grants(conn, apikey_id):
        if not grant["enabled"]:
            continue  # service temporairement désactivé pour ce client
        backend = await get_backend(conn, owner_login, grant["backend_id"])
        if backend is None or not backend["enabled"] or backend["namespace"] != namespace:
            continue
        if not _curation_allows(grant["expose_mode"], grant["expose"] or [], original):
            # namespace unique par apikey (contrainte registre) : une fois le namespace
            # trouvé, aucun autre grant ne peut autoriser cet appel → refus définitif.
            return None
        match = next(
            (p for p in await list_primitives(conn, grant["backend_id"], kind)
             if p["original_name"] == original),
            None,
        )
        if match is None or match["quarantined"]:
            return None
        # Enforcement par scope (spec 24 §4) : la primitive déclare son scope requis
        # dans sa definition ; le grant accorde un ensemble de scopes. NULL côté grant
        # = pas d'enforcement (backends externes inchangés). Deny-by-default sinon.
        required_scope = (match["definition"] or {}).get("scope")
        grant_scopes = grant.get("scopes")
        if required_scope and grant_scopes is not None and required_scope not in grant_scopes:
            return None
        return CallTarget(
            backend_id=grant["backend_id"],
            original_name=original,
            url=backend["url"],
            transport=backend["transport"],
            backend_key_id=grant["backend_key_id"],
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
        conn, apikey_id=apikey_id, owner_login=owner_login,
        namespace=namespace, original=original, kind=kind,
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
        conn, apikey_id=apikey_id, owner_login=owner_login,
        namespace=namespace, original=original, kind=kind,
    )
