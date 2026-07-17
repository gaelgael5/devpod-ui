"""Empreinte de la config agents d'un workspace — cœur du resync idempotent.

Objectif : ne rotationner les clefs MCP et réécrire les fichiers que lorsque la
config RÉELLE change. On hache tout ce qui détermine le rendu SAUF le token (qui
rotationne à chaque livraison) et le `home` du conteneur (une image qui change le
home passe par un recreate → `up`, qui livre toujours).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

# Colonnes d'un type d'agent qui influencent le fichier rendu (le reste — enabled,
# filename, timestamps — n'entre pas dans le contenu déposé).
_AGENT_RENDER_KEYS = ("id", "template", "target_path", "mode")


def compute_agent_fingerprint(
    *,
    agent_rows: Iterable[Mapping[str, Any]],
    profiles: Iterable[tuple[str, str]],
    mcp_url: str,
    project_root: str,
    ws_name: str,
    owner: str,
    ws_id: str,
) -> str:
    """Hash SHA-256 canonique des entrées de rendu (hors token/home).

    `profiles` = (id, nom) des profils exposés — un serveur MCP par profil.
    """
    payload = {
        "profiles": sorted([list(p) for p in profiles]),
        "agents": sorted(
            [{k: str(row.get(k, "")) for k in _AGENT_RENDER_KEYS} for row in agent_rows],
            key=lambda d: d["id"],
        ),
        "mcp_url": mcp_url,
        "project_root": project_root,
        "ws_name": ws_name,
        "owner": owner,
        "ws_id": ws_id,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
