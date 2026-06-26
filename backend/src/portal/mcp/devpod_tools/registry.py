"""Registre des primitives du backend MCP interne `devpod` (spec 24 §5).

Chaque entrée est la `definition` au format tool MCP, augmentée de la clé `scope`
(read/write/exec/admin) — le contrat de la primitive. Le scope est inerte côté
client (qui ne lit que name/description/inputSchema) et sert à l'enforcement §4.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

DEVPOD_PRIMITIVES: dict[str, dict[str, Any]] = {
    "workspace_list": {
        "description": "Liste les workspaces avec leur statut, node et recette.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["running", "stopped", "all"],
                    "default": "all",
                    "description": "Filtre optionnel sur le statut.",
                }
            },
        },
        "scope": "read",
    },
    "workspace_status": {
        "description": "Retourne l'état de santé d'un workspace : conteneur et agent.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {"workspace": {"type": "string", "description": "Nom du workspace."}},
        },
        "scope": "read",
    },
}


def definition_hash(defn: dict[str, Any]) -> str:
    """Hash stable d'une definition (JSON canonique) pour la quarantaine du catalogue."""
    return hashlib.sha256(json.dumps(defn, sort_keys=True).encode()).hexdigest()
