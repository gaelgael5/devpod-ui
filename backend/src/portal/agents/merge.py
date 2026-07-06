"""Fusion du connecteur MCP dans un fichier de config partagé (spec 35b, mode `merge`).

Le portail ne possède que **ses** serveurs (préfixe `portal-`). Le merge :
- upsert les serveurs du fragment sous la clé de tête (`mcpServers` / `mcp_servers`) ;
- purge les serveurs `portal-*` périmés déjà présents ;
- ne touche JAMAIS une clé sans préfixe (serveur ajouté par l'utilisateur), ni les
  autres sections / commentaires du fichier.

Fichier absent → création minimale. Fichier existant **malformé** → `MergeError`
(fail-safe : l'appelant conserve l'original, il ne détruit rien).
"""

from __future__ import annotations

import json
import tomllib
from typing import Any, Literal

import tomlkit

Format = Literal["json", "toml"]


class MergeError(Exception):
    """Merge impossible (fichier existant illisible, fragment invalide, conflit)."""


def merge_config(
    existing: str | None,
    fragment: str,
    *,
    fmt: Format,
    servers_key: str,
    prefix: str = "portal-",
) -> str:
    """Fusionne `fragment` dans `existing` et retourne le contenu complet à écrire."""
    servers = _fragment_servers(fragment, fmt, servers_key, prefix)
    if fmt == "json":
        return _merge_json(existing, servers_key, servers, prefix)
    if fmt == "toml":
        return _merge_toml(existing, servers_key, servers, prefix)
    raise MergeError(f"format inconnu : {fmt!r}")


def _fragment_servers(fragment: str, fmt: Format, servers_key: str, prefix: str) -> dict[str, Any]:
    """Serveurs possédés par le portail extraits du fragment rendu (peut être vide)."""
    if not fragment.strip():
        return {}
    try:
        obj = json.loads(fragment) if fmt == "json" else tomllib.loads(fragment)
    except Exception as exc:
        raise MergeError(f"fragment {fmt} invalide : {type(exc).__name__}") from exc
    servers = obj.get(servers_key, {})
    if not isinstance(servers, dict):
        raise MergeError(f"fragment : '{servers_key}' n'est pas une table")
    for name in servers:
        if not name.startswith(prefix):
            raise MergeError(f"serveur de fragment sans préfixe '{prefix}' : {name!r}")
    return servers


def _reconcile(container: Any, servers: dict[str, Any], prefix: str) -> None:
    """Purge les entrées `prefix*` du conteneur puis upsert les serveurs courants.

    Fonctionne pour un dict natif (JSON) comme pour une table tomlkit (TOML), les
    deux exposant l'interface MutableMapping.
    """
    for name in [k for k in list(container.keys()) if k.startswith(prefix)]:
        del container[name]
    for name, value in servers.items():
        container[name] = value


def _merge_json(
    existing: str | None, servers_key: str, servers: dict[str, Any], prefix: str
) -> str:
    if existing and existing.strip():
        try:
            obj = json.loads(existing)
        except Exception as exc:
            raise MergeError(f"JSON existant illisible : {type(exc).__name__}") from exc
    else:
        obj = {}
    if not isinstance(obj, dict):
        raise MergeError("le fichier JSON existant n'est pas un objet")

    existed = servers_key in obj
    container = obj.get(servers_key, {})
    if not isinstance(container, dict):
        raise MergeError(f"'{servers_key}' existant n'est pas un objet")
    _reconcile(container, servers, prefix)

    obj[servers_key] = container
    if not container and not existed:
        obj.pop(servers_key, None)
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def _merge_toml(
    existing: str | None, servers_key: str, servers: dict[str, Any], prefix: str
) -> str:
    if existing and existing.strip():
        try:
            doc = tomlkit.parse(existing)
        except Exception as exc:
            raise MergeError(f"TOML existant illisible : {type(exc).__name__}") from exc
    else:
        doc = tomlkit.document()

    existed = servers_key in doc
    container = doc.get(servers_key)
    if container is None:
        container = tomlkit.table()
    elif not isinstance(container, dict):
        raise MergeError(f"'{servers_key}' existant n'est pas une table")
    _reconcile(container, servers, prefix)

    doc[servers_key] = container
    if len(container) == 0 and not existed:
        del doc[servers_key]
    return tomlkit.dumps(doc)
