# Passerelle MCP — outils `devpod`

> Généré depuis `portal.mcp.devpod_tools.registry` — **ne pas éditer à la main**.
> Contrat des primitives de pilotage des workspaces (spec 24). Régénérer via
> `uv run python scripts/gen_mcp_docs.py`.

## `devpod__workspace_list`

- **Scope** : `read`
- **Description** : Liste les workspaces avec leur statut, node et recette.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "status": {
      "type": "string",
      "enum": [
        "running",
        "stopped",
        "all"
      ],
      "default": "all",
      "description": "Filtre optionnel sur le statut."
    }
  }
}
```

## `devpod__workspace_status`

- **Scope** : `read`
- **Description** : Retourne l'état de santé d'un workspace : conteneur et agent.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace"
  ],
  "properties": {
    "workspace": {
      "type": "string",
      "description": "Nom du workspace."
    }
  }
}
```

## `devpod__workspace_logs`

- **Scope** : `read`
- **Description** : Retourne les logs d'un workspace (setup d'installation, agent ou conteneur).
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    },
    "source": {
      "type": "string",
      "enum": [
        "setup",
        "agent",
        "container"
      ],
      "default": "container"
    },
    "lines": {
      "type": "integer",
      "default": 200,
      "minimum": 1
    },
    "since": {
      "type": "string",
      "description": "Réservé v1 (non appliqué)."
    }
  }
}
```

## `devpod__workspace_resources`

- **Scope** : `read`
- **Description** : Retourne la consommation CPU / mémoire / disque du conteneur du workspace.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    }
  }
}
```

## `devpod__workspace_git_status`

- **Scope** : `read`
- **Description** : Retourne l'état git du workspace (branche, fichiers modifiés, diff optionnel).
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    },
    "with_diff": {
      "type": "boolean",
      "default": false
    }
  }
}
```

## `devpod__workspace_git_commit`

- **Scope** : `exec`
- **Description** : Commit conventionnel sur la branche dev (garde de branche). Push optionnel.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace",
    "message"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    },
    "message": {
      "type": "string",
      "description": "Message commit conventionnel FR."
    },
    "files": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "push": {
      "type": "boolean",
      "default": false
    }
  }
}
```

## `devpod__workspace_tree`

- **Scope** : `read`
- **Description** : Liste l'arborescence du workspace à partir d'un chemin, avec profondeur et exclusions.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    },
    "path": {
      "type": "string",
      "default": ".",
      "description": "Chemin relatif à la racine du workspace (I-5)."
    },
    "depth": {
      "type": "integer",
      "default": 2,
      "minimum": 1
    },
    "ignore": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "default": [
        ".git",
        ".venv",
        "node_modules",
        "__pycache__"
      ]
    }
  }
}
```

## `devpod__workspace_read_file`

- **Scope** : `read`
- **Description** : Lit le contenu d'un fichier du workspace.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace",
    "path"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    },
    "path": {
      "type": "string",
      "description": "Chemin relatif à la racine (I-5)."
    }
  }
}
```

## `devpod__workspace_mkdir`

- **Scope** : `write`
- **Description** : Crée un répertoire (et ses parents) dans le workspace.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace",
    "path"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    },
    "path": {
      "type": "string",
      "description": "Chemin relatif à la racine (I-5)."
    }
  }
}
```

## `devpod__workspace_write_file`

- **Scope** : `write`
- **Description** : Écrit un fichier dans le workspace de façon atomique (tempfile + rename).
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace",
    "path",
    "content"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    },
    "path": {
      "type": "string",
      "description": "Chemin relatif à la racine (I-5)."
    },
    "content": {
      "type": "string"
    },
    "create_dirs": {
      "type": "boolean",
      "default": true,
      "description": "Crée les répertoires parents manquants."
    }
  }
}
```

## `devpod__workspace_exec`

- **Scope** : `exec`
- **Description** : Exécute une commande non-interactive dans le conteneur du workspace et retourne sa sortie.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace",
    "command"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    },
    "command": {
      "type": "string",
      "description": "Commande shell à exécuter."
    },
    "cwd": {
      "type": "string",
      "description": "Répertoire de travail relatif à la racine (défaut : racine)."
    },
    "timeout_s": {
      "type": "integer",
      "default": 60,
      "minimum": 1
    }
  }
}
```

## `devpod__workspace_start`

- **Scope** : `admin`
- **Description** : Démarre le conteneur du workspace.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    }
  }
}
```

## `devpod__workspace_stop`

- **Scope** : `admin`
- **Description** : Arrête le conteneur du workspace.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    }
  }
}
```

## `devpod__workspace_restart`

- **Scope** : `admin`
- **Description** : Redémarre le conteneur du workspace.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    }
  }
}
```

## `devpod__session_open`

- **Scope** : `exec`
- **Description** : Ouvre (idempotent) une session tmux nommée et y lance une commande agent.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace",
    "command"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    },
    "command": {
      "type": "string",
      "description": "Commande lançant l'agent (ex. 'claude', 'codex'). Agnostique."
    },
    "name": {
      "type": "string",
      "default": "main",
      "description": "Nom de la session tmux."
    },
    "cwd": {
      "type": "string",
      "description": "Répertoire de travail relatif (I-5)."
    }
  }
}
```

## `devpod__session_send`

- **Scope** : `exec`
- **Description** : Envoie du texte vers le stdin de l'agent d'une session (send-keys). N'attend pas de sortie : lire via session_capture.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace",
    "text"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    },
    "session": {
      "type": "string",
      "default": "main"
    },
    "text": {
      "type": "string"
    },
    "submit": {
      "type": "boolean",
      "default": true,
      "description": "Si true valide l'entrée (Enter), sinon stage sans valider."
    },
    "_origin": {
      "type": "string",
      "description": "RÉSERVÉ (I-7) — origine de la tâche. Non câblé en v1."
    },
    "_depth": {
      "type": "integer",
      "description": "RÉSERVÉ (I-7) — profondeur de récursion. Non câblé en v1."
    }
  }
}
```

## `devpod__session_interrupt`

- **Scope** : `exec`
- **Description** : Envoie un signal d'interruption (Ctrl-C) au premier plan d'une session.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    },
    "session": {
      "type": "string",
      "default": "main"
    }
  }
}
```

## `devpod__session_close`

- **Scope** : `exec`
- **Description** : Termine une session tmux nommée et le process qu'elle héberge.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace",
    "session"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    },
    "session": {
      "type": "string"
    }
  }
}
```

## `devpod__session_capture`

- **Scope** : `read`
- **Description** : Capture le buffer brut du pane d'une session (capture-pane).
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    },
    "session": {
      "type": "string",
      "default": "main"
    },
    "lines": {
      "type": "integer",
      "default": 200,
      "minimum": 1,
      "description": "Nombre de lignes à remonter."
    }
  }
}
```

## `devpod__session_list`

- **Scope** : `read`
- **Description** : Liste les sessions actives d'un workspace.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    }
  }
}
```

## `devpod__session_get`

- **Scope** : `read`
- **Description** : Métadonnées d'une session (nom, commande, état, pane, uptime).
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    },
    "session": {
      "type": "string",
      "default": "main"
    }
  }
}
```

## `devpod__node_list`

- **Scope** : `read`
- **Description** : Liste les nodes enrôlés et leur disponibilité.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {}
}
```

## `devpod__operations_get`

- **Scope** : `read`
- **Description** : Retourne l'état, la progression et le résultat d'une opération asynchrone.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "operation_id"
  ],
  "properties": {
    "operation_id": {
      "type": "string"
    }
  }
}
```

## `devpod__operations_list`

- **Scope** : `read`
- **Description** : Liste les opérations en cours, filtrables par workspace.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "workspace": {
      "type": "string"
    }
  }
}
```

## `devpod__portal_reload`

- **Scope** : `admin`
- **Description** : Reconnecte le portail à un workspace dont le conteneur tourne déjà (post mise à jour du portail).
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    }
  }
}
```

## `devpod__workspace_get`

- **Scope** : `read`
- **Description** : Retourne le descripteur complet d'un workspace (repo, branche, recette, node, sessions, dates).
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    }
  }
}
```

## `devpod__workspace_create`

- **Scope** : `admin`
- **Description** : Crée un workspace depuis un repo et une recette. Asynchrone : retourne un operation_id.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "name",
    "repo"
  ],
  "properties": {
    "name": {
      "type": "string"
    },
    "repo": {
      "type": "string",
      "description": "URL du dépôt git."
    },
    "branch": {
      "type": "string",
      "default": "dev"
    },
    "recipe": {
      "type": "string",
      "description": "Recette. Défaut : auto-détection."
    },
    "node": {
      "type": "string",
      "description": "Node cible. Défaut : placement auto."
    }
  }
}
```

## `devpod__workspace_delete`

- **Scope** : `admin`
- **Description** : Supprime un workspace et son conteneur. Destructif.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace",
    "confirm"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    },
    "confirm": {
      "type": "boolean",
      "description": "Doit valoir true (garde anti-suppression)."
    }
  }
}
```
