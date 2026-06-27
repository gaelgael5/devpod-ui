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
    "workspace_logs": {
        "description": (
            "Retourne les logs d'un workspace (setup d'installation, agent ou conteneur)."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {
                "workspace": {"type": "string"},
                "source": {
                    "type": "string",
                    "enum": ["setup", "agent", "container"],
                    "default": "container",
                },
                "lines": {"type": "integer", "default": 200, "minimum": 1},
                "since": {"type": "string", "description": "Réservé v1 (non appliqué)."},
            },
        },
        "scope": "read",
    },
    "workspace_resources": {
        "description": "Retourne la consommation CPU / mémoire / disque du conteneur du workspace.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {"workspace": {"type": "string"}},
        },
        "scope": "read",
    },
    "workspace_git_status": {
        "description": (
            "Retourne l'état git du workspace "
            "(branche, fichiers modifiés, diff optionnel)."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {
                "workspace": {"type": "string"},
                "with_diff": {"type": "boolean", "default": False},
            },
        },
        "scope": "read",
    },
    "workspace_git_commit": {
        "description": (
            "Commit conventionnel sur la branche dev (garde de branche). "
            "Push optionnel."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace", "message"],
            "properties": {
                "workspace": {"type": "string"},
                "message": {
                    "type": "string",
                    "description": "Message commit conventionnel FR.",
                },
                "files": {"type": "array", "items": {"type": "string"}},
                "push": {"type": "boolean", "default": False},
            },
        },
        "scope": "exec",
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
    "workspace_secrets_list": {
        "description": (
            "Liste les références de secrets (${vault://...}) liées au workspace. "
            "Noms uniquement, jamais de valeurs."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {"workspace": {"type": "string"}},
        },
        "scope": "read",
    },
    "workspace_secrets_bind": {
        "description": (
            "Lie une référence ${vault://...} à une cible (env var) du workspace. "
            "Résolution interne au runtime ; aucune valeur retournée."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace", "reference", "target"],
            "properties": {
                "workspace": {"type": "string"},
                "reference": {
                    "type": "string",
                    "description": "Référence vault, ex. '${vault://bloc/nom}'.",
                },
                "target": {"type": "string", "description": "Variable d'environnement cible."},
            },
        },
        "scope": "write",
    },
    "workspace_mkdir": {
        "description": "Crée un répertoire (et ses parents) dans le workspace.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace", "path"],
            "properties": {
                "workspace": {"type": "string"},
                "path": {"type": "string", "description": "Chemin relatif à la racine (I-5)."},
            },
        },
        "scope": "write",
    },
    "workspace_write_file": {
        "description": "Écrit un fichier dans le workspace de façon atomique (tempfile + rename).",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace", "path", "content"],
            "properties": {
                "workspace": {"type": "string"},
                "path": {"type": "string", "description": "Chemin relatif à la racine (I-5)."},
                "content": {"type": "string"},
                "create_dirs": {
                    "type": "boolean",
                    "default": True,
                    "description": "Crée les répertoires parents manquants.",
                },
            },
        },
        "scope": "write",
    },
    "workspace_exec": {
        "description": (
            "Exécute une commande non-interactive dans le conteneur du workspace et "
            "retourne sa sortie."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace", "command"],
            "properties": {
                "workspace": {"type": "string"},
                "command": {"type": "string", "description": "Commande shell à exécuter."},
                "cwd": {
                    "type": "string",
                    "description": "Répertoire de travail relatif à la racine (défaut : racine).",
                },
                "timeout_s": {"type": "integer", "default": 60, "minimum": 1},
            },
        },
        "scope": "exec",
    },
    "workspace_start": {
        "description": (
            "Démarre le conteneur du workspace. "
            "Asynchrone : retourne un operation_id."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {"workspace": {"type": "string"}},
        },
        "scope": "admin",
    },
    "workspace_stop": {
        "description": (
            "Arrête le conteneur du workspace. "
            "Asynchrone : retourne un operation_id."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {"workspace": {"type": "string"}},
        },
        "scope": "admin",
    },
    "workspace_restart": {
        "description": (
            "Redémarre le conteneur du workspace. "
            "Asynchrone : retourne un operation_id."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {"workspace": {"type": "string"}},
        },
        "scope": "admin",
    },
    "session_open": {
        "description": "Ouvre (idempotent) une session tmux nommée et y lance une commande agent.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace", "command"],
            "properties": {
                "workspace": {"type": "string"},
                "command": {
                    "type": "string",
                    "description": "Commande lançant l'agent (ex. 'claude', 'codex'). Agnostique.",
                },
                "name": {
                    "type": "string",
                    "default": "main",
                    "description": "Nom de la session tmux.",
                },
                "cwd": {"type": "string", "description": "Répertoire de travail relatif (I-5)."},
            },
        },
        "scope": "exec",
    },
    "session_send": {
        "description": (
            "Envoie du texte vers le stdin de l'agent d'une session (send-keys). "
            "N'attend pas de sortie : lire via session_capture."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace", "text"],
            "properties": {
                "workspace": {"type": "string"},
                "session": {"type": "string", "default": "main"},
                "text": {"type": "string"},
                "submit": {
                    "type": "boolean",
                    "default": True,
                    "description": "Si true valide l'entrée (Enter), sinon stage sans valider.",
                },
                "_origin": {
                    "type": "string",
                    "description": "RÉSERVÉ (I-7) — origine de la tâche. Non câblé en v1.",
                },
                "_depth": {
                    "type": "integer",
                    "description": "RÉSERVÉ (I-7) — profondeur de récursion. Non câblé en v1.",
                },
            },
        },
        "scope": "exec",
    },
    "session_interrupt": {
        "description": "Envoie un signal d'interruption (Ctrl-C) au premier plan d'une session.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {
                "workspace": {"type": "string"},
                "session": {"type": "string", "default": "main"},
            },
        },
        "scope": "exec",
    },
    "session_close": {
        "description": "Termine une session tmux nommée et le process qu'elle héberge.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace", "session"],
            "properties": {
                "workspace": {"type": "string"},
                "session": {"type": "string"},
            },
        },
        "scope": "exec",
    },
    "session_capture": {
        "description": "Capture le buffer brut du pane d'une session (capture-pane).",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {
                "workspace": {"type": "string"},
                "session": {"type": "string", "default": "main"},
                "lines": {
                    "type": "integer",
                    "default": 200,
                    "minimum": 1,
                    "description": "Nombre de lignes à remonter.",
                },
            },
        },
        "scope": "read",
    },
    "session_list": {
        "description": "Liste les sessions actives d'un workspace.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {"workspace": {"type": "string"}},
        },
        "scope": "read",
    },
    "session_get": {
        "description": "Métadonnées d'une session (nom, commande, état, pane, uptime).",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {
                "workspace": {"type": "string"},
                "session": {"type": "string", "default": "main"},
            },
        },
        "scope": "read",
    },
    "node_list": {
        "description": "Liste les nodes enrôlés et leur disponibilité.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
        "scope": "read",
    },
    "operations_get": {
        "description": "Retourne l'état, la progression et le résultat d'une opération asynchrone.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["operation_id"],
            "properties": {"operation_id": {"type": "string"}},
        },
        "scope": "read",
    },
    "operations_list": {
        "description": "Liste les opérations en cours, filtrables par workspace.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"workspace": {"type": "string"}},
        },
        "scope": "read",
    },
    "portal_reload": {
        "description": (
            "Reconnecte le portail à un workspace dont le conteneur tourne déjà "
            "(post mise à jour du portail)."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {"workspace": {"type": "string"}},
        },
        "scope": "admin",
    },
    "workspace_get": {
        "description": (
            "Retourne le descripteur complet d'un workspace "
            "(repo, branche, recette, node, sessions, dates)."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {"workspace": {"type": "string"}},
        },
        "scope": "read",
    },
    "workspace_create": {
        "description": (
            "Crée un workspace depuis un repo et une recette. "
            "Asynchrone : retourne un operation_id."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "repo"],
            "properties": {
                "name": {"type": "string"},
                "repo": {"type": "string", "description": "URL du dépôt git."},
                "branch": {"type": "string", "default": "dev"},
                "recipe": {"type": "string", "description": "Recette. Défaut : auto-détection."},
                "node": {"type": "string", "description": "Node cible. Défaut : placement auto."},
            },
        },
        "scope": "admin",
    },
    "workspace_delete": {
        "description": "Supprime un workspace et son conteneur. Destructif.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace", "confirm"],
            "properties": {
                "workspace": {"type": "string"},
                "confirm": {"type": "boolean", "description": "Doit valoir true (garde anti-suppression)."},
            },
        },
        "scope": "admin",
    },
    "workspace_apply_recipe": {
        "description": (
            "Applique/met à jour une recette (Dev Container Features) sur un workspace "
            "existant. Asynchrone (recréation)."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace", "recipe"],
            "properties": {
                "workspace": {"type": "string"},
                "recipe": {"type": "string"},
            },
        },
        "scope": "admin",
    },
    "workspace_profile_set": {
        "description": (
            "Applique un profil VS Code (extensions et réglages Open VSX) au workspace "
            "(recréation)."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace", "profile"],
            "properties": {
                "workspace": {"type": "string"},
                "profile": {"type": "string", "description": "Identifiant du profil VS Code."},
            },
        },
        "scope": "write",
    },
}


def definition_hash(defn: dict[str, Any]) -> str:
    """Hash stable d'une definition (JSON canonique) pour la quarantaine du catalogue."""
    return hashlib.sha256(json.dumps(defn, sort_keys=True).encode()).hexdigest()
