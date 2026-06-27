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
    "workspace_tree": {
        "description": (
            "Liste l'arborescence du workspace à partir d'un chemin, avec profondeur "
            "et exclusions."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {
                "workspace": {"type": "string"},
                "path": {
                    "type": "string",
                    "default": ".",
                    "description": "Chemin relatif à la racine du workspace (I-5).",
                },
                "depth": {"type": "integer", "default": 2, "minimum": 1},
                "ignore": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [".git", ".venv", "node_modules", "__pycache__"],
                },
            },
        },
        "scope": "read",
    },
    "workspace_read_file": {
        "description": "Lit le contenu d'un fichier du workspace.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace", "path"],
            "properties": {
                "workspace": {"type": "string"},
                "path": {"type": "string", "description": "Chemin relatif à la racine (I-5)."},
            },
        },
        "scope": "read",
    },
}


def definition_hash(defn: dict[str, Any]) -> str:
    """Hash stable d'une definition (JSON canonique) pour la quarantaine du catalogue."""
    return hashlib.sha256(json.dumps(defn, sort_keys=True).encode()).hexdigest()
