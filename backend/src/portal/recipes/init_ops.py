"""Opérations pures des recipes `type: initialize` — appliquées CÔTÉ PORTAIL.

Le conteneur du workspace n'exécute que du sh (cat/base64/tar/cp/mv) : toute la
logique JSON vit ici, en stdlib, testable sans SSH ni conteneur.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


def split_node(node: str) -> list[str]:
    """'$.a.b' -> ['a', 'b']. Suppose un dot-path déjà validé en amont."""
    if not node.startswith("$."):
        raise ValueError(f"invalid node path: {node!r}")
    return node[2:].split(".")


def apply_replace(root: dict[str, Any], node: str, value: Any) -> None:
    """Pose (ou écrase) `value` au chemin `node`, en créant les dicts intermédiaires."""
    keys = split_node(node)
    cur = root
    for k in keys[:-1]:
        nxt = cur.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[k] = nxt
        cur = nxt
    cur[keys[-1]] = value


def apply_remove(root: dict[str, Any], node: str) -> None:
    """Supprime le nœud `node` s'il existe — no-op sinon."""
    keys = split_node(node)
    cur: Any = root
    for k in keys[:-1]:
        if not isinstance(cur, dict) or k not in cur:
            return
        cur = cur[k]
    if isinstance(cur, dict) and keys[-1] in cur:
        del cur[keys[-1]]


def sentinel_location(
    spec: dict[str, Any], *, first_copy_source_is_file: bool = False
) -> tuple[str | None, str]:
    """Emplacement du témoin : (base, relatif) — base=None signifie $HOME du conteneur.

    Mêmes règles que l'ancien moteur embarqué (compat sentinelles déjà posées) :
    dossier parent de la première cible `transform`, sinon dossier cible de la
    première `copy` (ou son parent si la source est un simple fichier), sinon
    le home du workspace.
    """
    name = f"{spec['recipe_id']}@{spec['version']}"
    rel = f".portal/{name}"
    transforms = spec.get("transform") or []
    copies = spec.get("copy") or []
    if transforms:
        return str(PurePosixPath(transforms[0]["target"]["file"]).parent), rel
    if copies:
        target = PurePosixPath(copies[0]["target"])
        if first_copy_source_is_file:
            return str(target.parent), rel
        return str(target), rel
    return None, rel
