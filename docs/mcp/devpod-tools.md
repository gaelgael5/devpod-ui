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
