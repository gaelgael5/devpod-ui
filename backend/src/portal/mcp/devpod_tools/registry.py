"""Registre des primitives du backend MCP interne `devpod` (spec 24 §5).

Chaque entrée est la `definition` au format tool MCP, augmentée de la clé `scope`
(read/write/exec/admin) — le contrat de la primitive. Le scope est inerte côté
client (qui ne lit que name/description/inputSchema) et sert à l'enforcement §4.

Vocabulaire d'impact (ligne "Impact:" de chaque description) :
  read-only           : aucune mutation (lecture seule)
  write-safe          : modifie fichiers ou config, ne touche pas aux conteneurs
  non-destructive     : reconnexion ou opération sans coupure de session
  destructive-sessions: redémarre ou recrée le conteneur → sessions SSH/tmux coupées,
                        travail en cours perdu ; appeler session_list avant d'exécuter
  destructive-data    : supprime workspace ou volumes → données perdues définitivement
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

DEVPOD_PRIMITIVES: dict[str, dict[str, Any]] = {
    "workspace_list": {
        "description": (
            "Liste les workspaces avec leur statut, node et recette. "
            "Impact: read-only — aucune mutation."
        ),
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
        "description": (
            "Retourne l'état de santé d'un workspace : conteneur et agent. "
            "Impact: read-only — aucune mutation."
        ),
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
            "Retourne les logs d'un workspace (setup d'installation, agent ou conteneur). "
            "Impact: read-only — aucune mutation."
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
        "description": (
            "Retourne la consommation CPU / mémoire / disque du conteneur du workspace. "
            "Impact: read-only — aucune mutation."
        ),
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
            "(branche, fichiers modifiés, diff optionnel). "
            "Impact: read-only — aucune mutation."
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
            "Push optionnel. "
            "Impact: write-safe — git add/commit/push dans le conteneur ; "
            "le conteneur n'est pas redémarré."
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
            "et exclusions. "
            "Impact: read-only — aucune mutation."
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
        "description": (
            "Lit le contenu d'un fichier du workspace. "
            "Impact: read-only — aucune mutation."
        ),
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
            "Noms uniquement, jamais de valeurs. "
            "Impact: read-only — noms uniquement, aucune valeur exposée."
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
            "Résolution interne au runtime ; aucune valeur retournée. "
            "Impact: write-safe — persiste un binding dans la config YAML utilisateur ; "
            "le conteneur n'est pas redémarré."
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
        "description": (
            "Crée un répertoire (et ses parents) dans le workspace. "
            "Impact: write-safe — crée des répertoires dans le conteneur ; "
            "pas de redémarrage."
        ),
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
        "description": (
            "Écrit un fichier dans le workspace de façon atomique (tempfile + rename). "
            "Impact: write-safe — écrit un fichier dans le conteneur ; "
            "pas de redémarrage."
        ),
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
            "retourne sa sortie. "
            "Impact: write-safe — exécute dans le conteneur en cours ; "
            "pas de redémarrage du conteneur."
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
    "workspace_reconnect": {
        "description": (
            "Lance un devpod up sur un workspace existant. Couvre deux cas d'usage : "
            "(1) relancer un workspace arrêté (équivalent workspace_start) — "
            "recharge le spec, résout les recipes/secrets/profile et redémarre le conteneur ; "
            "(2) rétablir le tunnel portail→VS Code après un redémarrage du portail "
            "sans toucher au conteneur ni aux sessions tmux actives. "
            "Différence avec workspace_restart : ne fait PAS de stop préalable — "
            "utiliser workspace_restart pour un redémarrage propre depuis un état running. "
            "Asynchrone : retourne un operation_id à interroger via operations_get."
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
            "Asynchrone : retourne un operation_id. "
            "Impact: destructive-sessions — stoppe le conteneur ; "
            "sessions SSH/tmux coupées, travail en cours perdu. "
            "Appeler session_list avant d'exécuter."
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
            "Asynchrone : retourne un operation_id. "
            "Impact: destructive-sessions — stop + devpod up ; "
            "sessions SSH/tmux coupées, travail en cours perdu. "
            "Appeler session_list avant d'exécuter."
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
        "description": (
            "Ouvre (idempotent) une session tmux nommée et y lance une commande agent. "
            "Impact: non-destructive — crée la session si absente ; "
            "aucune coupure si elle existe déjà."
        ),
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
            "N'attend pas de sortie : lire via session_capture. "
            "Impact: non-destructive — envoie du texte ; "
            "ne modifie ni le conteneur ni les autres sessions."
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
        "description": (
            "Envoie un signal d'interruption (Ctrl-C) au premier plan d'une session. "
            "Impact: non-destructive — Ctrl-C sur le process en premier plan uniquement."
        ),
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
        "description": (
            "Termine une session tmux nommée et le process qu'elle héberge. "
            "Impact: non-destructive (pour le workspace) — "
            "tue la session tmux via kill-session ; le conteneur reste en cours."
        ),
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
        "description": (
            "Capture le buffer brut du pane d'une session (capture-pane). "
            "Impact: read-only — lecture du buffer tmux, aucune mutation."
        ),
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
        "description": (
            "Liste les sessions actives d'un workspace. "
            "Impact: read-only — aucune mutation."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {"workspace": {"type": "string"}},
        },
        "scope": "read",
    },
    "session_get": {
        "description": (
            "Métadonnées d'une session (nom, commande, état, pane, uptime). "
            "Impact: read-only — aucune mutation."
        ),
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
        "description": (
            "Liste les nodes enrôlés et leur disponibilité. "
            "Impact: read-only — aucune mutation."
        ),
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
        "scope": "read",
    },
    "operations_get": {
        "description": (
            "Retourne l'état, la progression et le résultat d'une opération asynchrone. "
            "Impact: read-only — aucune mutation."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["operation_id"],
            "properties": {"operation_id": {"type": "string"}},
        },
        "scope": "read",
    },
    "operations_list": {
        "description": (
            "Liste les opérations en cours, filtrables par workspace. "
            "Impact: read-only — aucune mutation."
        ),
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
            "(post mise à jour du portail). "
            "Impact: non-destructive — appelle reconnect() uniquement si le conteneur "
            "est running ; refusé et reason='container_down' sinon."
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
            "(repo, branche, recette, node, sessions, dates). "
            "Impact: read-only — aucune mutation."
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
            "Asynchrone : retourne un operation_id. "
            "Impact: non-destructive — provisionne un nouveau workspace ; "
            "n'affecte pas les workspaces existants."
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
        "description": (
            "Supprime un workspace et son conteneur. "
            "Impact: destructive-data — devpod delete --force : "
            "conteneur + volumes + état devpod supprimés définitivement. Irréversible."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace", "confirm"],
            "properties": {
                "workspace": {"type": "string"},
                "confirm": {
                    "type": "boolean",
                    "description": "Doit valoir true (garde anti-suppression).",
                },
            },
        },
        "scope": "admin",
    },
    "workspace_apply_recipe": {
        "description": (
            "Applique/met à jour une recette (Dev Container Features) sur un workspace "
            "existant. Asynchrone (recréation). "
            "Impact: destructive-sessions — delete + recréation complète du conteneur ; "
            "sessions SSH/tmux coupées, travail en cours perdu, repo re-cloné. "
            "Appeler session_list avant d'exécuter."
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
            "(recréation). "
            "Impact: destructive-sessions — delete + recréation complète du conteneur ; "
            "sessions SSH/tmux coupées, travail en cours perdu. "
            "Appeler session_list avant d'exécuter."
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
    # -----------------------------------------------------------------------
    # Galerie docker-compose
    # -----------------------------------------------------------------------
    "compose_template_list": {
        "description": (
            "Liste les templates docker-compose disponibles. "
            "Impact: read-only — aucune mutation."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "tag": {"type": "string", "description": "Filtre optionnel sur un tag."},
            },
        },
        "scope": "read",
    },
    "compose_template_get": {
        "description": (
            "Retourne le descripteur complet d'un template (YAML inclus). "
            "Impact: read-only — aucune mutation."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["template_id"],
            "properties": {
                "template_id": {"type": "string"},
            },
        },
        "scope": "read",
    },
    "compose_template_create": {
        "description": (
            "Crée un nouveau template docker-compose dans la galerie. "
            "Le YAML est validé (ports codés en dur interdits, bind-mounts absolus interdits). "
            "Impact: write-safe — enregistre en base ; aucun conteneur créé ou modifié."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "name", "compose_content"],
            "properties": {
                "id": {"type": "string", "description": "Slug du template (^[a-z0-9-]+$)."},
                "name": {"type": "string"},
                "description": {"type": "string", "default": ""},
                "tags": {"type": "array", "items": {"type": "string"}, "default": []},
                "version": {"type": "string", "default": "1"},
                "compose_content": {
                    "type": "string",
                    "description": "Contenu YAML du docker-compose.yml.",
                },
                "parameters": {
                    "type": "array",
                    "items": {"type": "object"},
                    "default": [],
                    "description": "Paramètres du template (type string/number/bool/enum/secret).",
                },
            },
        },
        "scope": "admin",
    },
    "compose_template_update": {
        "description": (
            "Met à jour un template existant. Seuls les champs fournis sont modifiés "
            "(compose_content requis ; les autres reprennent la valeur existante si absents). "
            "Impact: write-safe — met à jour la définition en base ; "
            "aucun conteneur créé ou modifié."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "compose_content"],
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "version": {"type": "string"},
                "compose_content": {"type": "string"},
                "parameters": {"type": "array", "items": {"type": "object"}},
            },
        },
        "scope": "admin",
    },
    "compose_service_list": {
        "description": (
            "Liste les déploiements compose de l'utilisateur, filtrables par nœud. "
            "Impact: read-only — aucune mutation."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "node_id": {"type": "string", "description": "Filtre optionnel sur le nœud."},
            },
        },
        "scope": "read",
    },
    "compose_service_start": {
        "description": (
            "Démarre un template docker-compose sur une machine de test. "
            "Les ports alias (alias>N:M) sont alloués automatiquement. "
            "Impact: non-destructive — docker compose up ; "
            "crée les conteneurs s'ils n'existent pas, sans toucher aux autres déploiements."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["template_id", "node_id", "name"],
            "properties": {
                "template_id": {"type": "string"},
                "node_id": {"type": "string", "description": "ID du nœud cible (node_list)."},
                "name": {"type": "string", "description": "Slug du déploiement."},
                "env_values": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "default": {},
                    "description": "Valeurs des paramètres non-port.",
                },
            },
        },
        "scope": "exec",
    },
    "compose_service_stop": {
        "description": (
            "Arrête les conteneurs d'un déploiement (docker compose stop). "
            "Impact: destructive-sessions — conteneurs stoppés, volumes conservés, "
            "connexions coupées. "
            "Appeler session_list avant d'exécuter."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["deployment_id"],
            "properties": {"deployment_id": {"type": "string"}},
        },
        "scope": "exec",
    },
    "compose_service_restart": {
        "description": (
            "Redémarre les conteneurs d'un déploiement (docker compose restart). "
            "Impact: destructive-sessions — conteneurs redémarrés, connexions coupées. "
            "Appeler session_list avant d'exécuter."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["deployment_id"],
            "properties": {"deployment_id": {"type": "string"}},
        },
        "scope": "exec",
    },
    "compose_service_logs": {
        "description": (
            "Retourne les logs d'un déploiement compose. "
            "Impact: read-only — aucune mutation."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["deployment_id"],
            "properties": {
                "deployment_id": {"type": "string"},
                "service": {
                    "type": "string",
                    "description": "Nom d'un service spécifique (optionnel).",
                },
                "tail": {"type": "integer", "default": 200, "minimum": 1},
            },
        },
        "scope": "read",
    },
    "compose_service_status": {
        "description": (
            "Rafraîchit et retourne le statut live d'un déploiement. "
            "Impact: read-only — aucune mutation."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["deployment_id"],
            "properties": {"deployment_id": {"type": "string"}},
        },
        "scope": "read",
    },
    "compose_service_down": {
        "description": (
            "Détruit un déploiement (docker compose down -v + nettoyage). "
            "Irréversible : confirm doit valoir true. "
            "Impact: destructive-data — docker compose down -v : "
            "conteneurs + volumes supprimés, données perdues définitivement."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["deployment_id", "confirm"],
            "properties": {
                "deployment_id": {"type": "string"},
                "confirm": {
                    "type": "boolean",
                    "description": "Doit valoir true (garde anti-suppression).",
                },
            },
        },
        "scope": "exec",
    },
    "workspace_messages": {
        "description": (
            "Liste les messages contextuels du workspace : machines de test disponibles, "
            "services docker-compose démarrés (ports, alias SSH, etc.). "
            "À lire en début de session pour connaître l'environnement de travail. "
            "Impact: read-only — aucune mutation."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace_name"],
            "properties": {
                "workspace_name": {
                    "type": "string",
                    "description": "Nom du workspace dont on veut lire les messages.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Nombre max de messages retournés (1-500, défaut 50).",
                    "default": 50,
                },
            },
        },
        "scope": "read",
    },
}


def definition_hash(defn: dict[str, Any]) -> str:
    """Hash stable d'une definition (JSON canonique) pour la quarantaine du catalogue."""
    return hashlib.sha256(json.dumps(defn, sort_keys=True).encode()).hexdigest()
