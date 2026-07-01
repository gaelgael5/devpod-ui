# Passerelle MCP — outils `devpod`

> Généré depuis `portal.mcp.devpod_tools.registry` — **ne pas éditer à la main**.
> Contrat des primitives de pilotage des workspaces (spec 24). Régénérer via
> `uv run python scripts/gen_mcp_docs.py`.

## `devpod__workspace_list`

- **Scope** : `read`
- **Description** : Liste les workspaces avec leur statut, node et recette. Impact: read-only — aucune mutation.
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
- **Description** : Retourne l'état de santé d'un workspace : conteneur et agent. Impact: read-only — aucune mutation.
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
- **Description** : Retourne les logs d'un workspace (setup d'installation, agent ou conteneur). Impact: read-only — aucune mutation.
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
      "description": "NON IMPLÉMENTÉ en v1 — ignoré. Filtrage à venir."
    }
  }
}
```

## `devpod__workspace_resources`

- **Scope** : `read`
- **Description** : Retourne la consommation CPU / mémoire / disque du conteneur du workspace. Impact: read-only — aucune mutation.
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
- **Description** : Retourne l'état git du workspace (branche, fichiers modifiés, diff optionnel). Impact: read-only — aucune mutation.
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
- **Description** : Commit conventionnel sur la branche dev (garde de branche). Push optionnel. Impact: write-safe — git add/commit/push dans le conteneur ; le conteneur n'est pas redémarré.
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
- **Description** : Liste l'arborescence du workspace à partir d'un chemin, avec profondeur et exclusions. Impact: read-only — aucune mutation.
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
- **Description** : Lit le contenu d'un fichier du workspace. Impact: read-only — aucune mutation.
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

## `devpod__workspace_secrets_list`

- **Scope** : `read`
- **Description** : Liste les références de secrets (${vault://...}) liées au workspace. Noms uniquement, jamais de valeurs. Impact: read-only — noms uniquement, aucune valeur exposée.
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

## `devpod__workspace_secrets_bind`

- **Scope** : `write`
- **Description** : Lie une référence ${vault://...} à une cible (env var) du workspace. Résolution interne au runtime ; aucune valeur retournée. Impact: write-safe — persiste un binding dans la config YAML utilisateur ; le conteneur n'est pas redémarré.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace",
    "reference",
    "target"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    },
    "reference": {
      "type": "string",
      "description": "Référence vault, ex. '${vault://bloc/nom}'."
    },
    "target": {
      "type": "string",
      "description": "Variable d'environnement cible."
    }
  }
}
```

## `devpod__workspace_mkdir`

- **Scope** : `write`
- **Description** : Crée un répertoire (et ses parents) dans le workspace. Impact: write-safe — crée des répertoires dans le conteneur ; pas de redémarrage.
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
- **Description** : Écrit un fichier dans le workspace de façon atomique (tempfile + rename). Impact: write-safe — écrit un fichier dans le conteneur ; pas de redémarrage.
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
- **Description** : Exécute une commande non-interactive dans le conteneur du workspace et retourne sa sortie. Impact: write-safe — exécute dans le conteneur en cours ; pas de redémarrage du conteneur. Note: stdout et stderr sont fusionnés dans le champ 'stdout' (v1) ; 'stderr' est toujours vide.
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

## `devpod__workspace_reconnect`

- **Scope** : `admin`
- **Description** : Lance un devpod up sur un workspace existant. Couvre deux cas d'usage : (1) relancer un workspace arrêté (équivalent workspace_start) — recharge le spec, résout les recipes/secrets/profile et redémarre le conteneur ; (2) rétablir le tunnel portail→VS Code après un redémarrage du portail sans toucher au conteneur ni aux sessions tmux actives. Différence avec workspace_restart : ne fait PAS de stop préalable — utiliser workspace_restart pour un redémarrage propre depuis un état running. Asynchrone : retourne un operation_id à interroger via operations_get.
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
- **Description** : Arrête le conteneur du workspace. Asynchrone : retourne un operation_id. Impact: destructive-sessions — stoppe le conteneur ; sessions SSH/tmux coupées, travail en cours perdu. Appeler session_list avant d'exécuter.
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
- **Description** : Redémarre le conteneur du workspace. Asynchrone : retourne un operation_id. Impact: destructive-sessions — stop + devpod up ; sessions SSH/tmux coupées, travail en cours perdu. Appeler session_list avant d'exécuter.
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
- **Description** : Ouvre (idempotent) une session tmux nommée et y lance une commande agent. Impact: non-destructive — crée la session si absente ; aucune coupure si elle existe déjà.
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
- **Description** : Envoie du texte vers le stdin de l'agent d'une session (send-keys). N'attend pas de sortie : lire via session_capture. Impact: non-destructive — envoie du texte ; ne modifie ni le conteneur ni les autres sessions.
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
- **Description** : Envoie un signal d'interruption (Ctrl-C) au premier plan d'une session. Impact: non-destructive — Ctrl-C sur le process en premier plan uniquement.
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
- **Description** : Termine une session tmux nommée et le process qu'elle héberge. Impact: non-destructive (pour le workspace) — tue la session tmux via kill-session ; le conteneur reste en cours.
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
- **Description** : Capture le buffer brut du pane d'une session (capture-pane). Impact: read-only — lecture du buffer tmux, aucune mutation.
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
- **Description** : Liste les sessions actives d'un workspace. Impact: read-only — aucune mutation.
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
- **Description** : Métadonnées d'une session (nom, commande, état, pane, uptime). Impact: read-only — aucune mutation.
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
- **Description** : Liste TOUS les hosts Docker de l'infra (enrôlés et machines de test générées), qualifiés par leur rôle. Outil de découverte d'infra : un seul appel suffit pour construire le modèle mental complet du fleet avant d'agir (logs, exec, déploiement). 

Chaque entrée inclut : node_id (stable, cohérent avec compose_service_list et workspace_list), role ('dev'=host enrôlé | 'test'=machine éphémère générée), host (adresse SSH/Docker), health (statut configuré ; reachable=null : probe live non implémenté), lifecycle (origin, ephemeral, linked_workspace). 

Paramètre optionnel `include` pour enrichir la réponse : - 'workload' : compteurs workspaces + compose_deployments par node ; - 'capacity', 'load', 'docker' : Vague B non collecté → null pour l'instant. Pour le modèle mental complet : include=['workload']. Impact: read-only — aucune mutation.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "include": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": [
          "workload",
          "capacity",
          "load",
          "docker"
        ]
      },
      "description": "Champs optionnels à inclure dans la réponse. 'workload' ajoute les compteurs workspaces/compose_deployments. 'capacity', 'load', 'docker' sont prévus (Vague B) mais renvoient null."
    }
  }
}
```

## `devpod__operations_get`

- **Scope** : `read`
- **Description** : Retourne l'état, la progression et le résultat d'une opération asynchrone. Impact: read-only — aucune mutation.
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
- **Description** : Liste les opérations en cours, filtrables par workspace. Impact: read-only — aucune mutation.
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
- **Description** : Reconnecte le portail à un workspace dont le conteneur tourne déjà (post mise à jour du portail). Impact: non-destructive — appelle reconnect() uniquement si le conteneur est running ; refusé et reason='container_down' sinon.
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
- **Description** : Retourne le descripteur complet d'un workspace (repo, branche, recette, node, sessions, dates). Impact: read-only — aucune mutation.
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
- **Description** : Crée un workspace depuis un repo et une liste de recettes. Si 'based_on' est fourni, les propriétés du workspace existant sont utilisées comme base et les paramètres explicitement fournis les écrasent. Asynchrone : retourne un operation_id. Impact: non-destructive — provisionne un nouveau workspace ; n'affecte pas les workspaces existants.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "name"
  ],
  "properties": {
    "name": {
      "type": "string"
    },
    "based_on": {
      "type": "string",
      "description": "Nom d'un workspace existant à utiliser comme modèle. Ses propriétés (repo, branch, recipes, etc.) sont copiées, puis écrasées par les paramètres explicitement fournis."
    },
    "repo": {
      "type": "string",
      "description": "URL du dépôt git."
    },
    "branch": {
      "type": "string",
      "default": "dev"
    },
    "recipes": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Recettes appliquées au build du conteneur (ordre respecté)."
    },
    "init_recipes": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Actions d'initialisation déclenchables à la demande (ex: claude-bypass-permissions)."
    },
    "ssh_key": {
      "type": "boolean",
      "default": false,
      "description": "Génère une clé SSH dédiée pour ce workspace."
    },
    "profile": {
      "type": "string",
      "description": "Profil VS Code au format 'scope/slug' (ex: 'shared/python-dev') ou 'slug' seul (scope shared implicite)."
    },
    "git_credential": {
      "type": "string",
      "description": "Nom du credential git (défini dans la config user) pour cloner un repo privé (ex: 'github-ssh')."
    },
    "node": {
      "type": "string",
      "description": "Node cible. Défaut : placement auto. Déprécié — cf. node_id."
    },
    "node_id": {
      "type": "string",
      "description": "ID du nœud cible (node_list). Alias de 'node'."
    }
  }
}
```

## `devpod__workspace_delete`

- **Scope** : `admin`
- **Description** : Supprime un workspace et son conteneur. Impact: destructive-data — devpod delete --force : conteneur + volumes + état devpod supprimés définitivement. Irréversible.
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

## `devpod__workspace_apply_recipe`

- **Scope** : `admin`
- **Description** : Applique/met à jour une recette (Dev Container Features) sur un workspace existant. Asynchrone (recréation). Impact: destructive-sessions — delete + recréation complète du conteneur ; sessions SSH/tmux coupées, travail en cours perdu, repo re-cloné. Appeler session_list avant d'exécuter.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace",
    "recipe"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    },
    "recipe": {
      "type": "string"
    }
  }
}
```

## `devpod__workspace_profile_set`

- **Scope** : `admin`
- **Description** : Applique un profil VS Code (extensions et réglages Open VSX) au workspace (recréation). Impact: destructive-sessions — delete + recréation complète du conteneur ; sessions SSH/tmux coupées, travail en cours perdu. Appeler session_list avant d'exécuter.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "workspace",
    "profile"
  ],
  "properties": {
    "workspace": {
      "type": "string"
    },
    "profile": {
      "type": "string",
      "description": "Identifiant du profil VS Code."
    }
  }
}
```

## `devpod__compose_template_list`

- **Scope** : `read`
- **Description** : Liste les templates docker-compose disponibles. Impact: read-only — aucune mutation.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "tag": {
      "type": "string",
      "description": "Filtre optionnel sur un tag."
    }
  }
}
```

## `devpod__compose_template_get`

- **Scope** : `read`
- **Description** : Retourne le descripteur complet d'un template (YAML inclus). Impact: read-only — aucune mutation.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "template_id"
  ],
  "properties": {
    "template_id": {
      "type": "string"
    }
  }
}
```

## `devpod__compose_template_create`

- **Scope** : `admin`
- **Description** : Crée un nouveau template docker-compose dans la galerie. Le YAML est validé (ports codés en dur interdits, bind-mounts absolus interdits). Impact: write-safe — enregistre en base ; aucun conteneur créé ou modifié.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "id",
    "name",
    "compose_content"
  ],
  "properties": {
    "id": {
      "type": "string",
      "description": "Slug du template (^[a-z0-9-]+$)."
    },
    "name": {
      "type": "string"
    },
    "description": {
      "type": "string",
      "default": ""
    },
    "tags": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "default": []
    },
    "version": {
      "type": "string",
      "default": "1"
    },
    "compose_content": {
      "type": "string",
      "description": "Contenu YAML du docker-compose.yml."
    },
    "parameters": {
      "type": "array",
      "items": {
        "type": "object"
      },
      "default": [],
      "description": "Paramètres du template (type string/number/bool/enum/secret)."
    }
  }
}
```

## `devpod__compose_template_update`

- **Scope** : `admin`
- **Description** : Met à jour un template existant. Seuls les champs fournis sont modifiés (compose_content requis ; les autres reprennent la valeur existante si absents). Impact: write-safe — met à jour la définition en base ; aucun conteneur créé ou modifié.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "id",
    "compose_content"
  ],
  "properties": {
    "id": {
      "type": "string"
    },
    "name": {
      "type": "string"
    },
    "description": {
      "type": "string"
    },
    "tags": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "version": {
      "type": "string"
    },
    "compose_content": {
      "type": "string"
    },
    "parameters": {
      "type": "array",
      "items": {
        "type": "object"
      }
    }
  }
}
```

## `devpod__compose_service_list`

- **Scope** : `read`
- **Description** : Liste les déploiements compose de l'utilisateur, filtrables par nœud. Le champ 'status' est déclaratif (issu de la DB) — appeler compose_service_status pour un état live. Impact: read-only — aucune mutation.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "node_id": {
      "type": "string",
      "description": "Filtre optionnel sur le nœud."
    }
  }
}
```

## `devpod__compose_service_start`

- **Scope** : `exec`
- **Description** : Démarre un template docker-compose sur une machine de test. Les ports alias (alias>N:M) sont alloués automatiquement. Impact: non-destructive — docker compose up ; crée les conteneurs s'ils n'existent pas, sans toucher aux autres déploiements.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "template_id",
    "node_id",
    "name"
  ],
  "properties": {
    "template_id": {
      "type": "string"
    },
    "node_id": {
      "type": "string",
      "description": "ID du nœud cible (node_list)."
    },
    "name": {
      "type": "string",
      "description": "Slug du déploiement."
    },
    "env_values": {
      "type": "object",
      "additionalProperties": {
        "type": "string"
      },
      "default": {},
      "description": "Valeurs des paramètres non-port."
    }
  }
}
```

## `devpod__compose_service_stop`

- **Scope** : `exec`
- **Description** : Arrête les conteneurs d'un déploiement (docker compose stop). Impact: destructive-sessions — conteneurs stoppés, volumes conservés, connexions coupées. Appeler session_list avant d'exécuter.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "deployment_id"
  ],
  "properties": {
    "deployment_id": {
      "type": "string"
    }
  }
}
```

## `devpod__compose_service_restart`

- **Scope** : `exec`
- **Description** : Redémarre les conteneurs d'un déploiement (docker compose restart). Impact: destructive-sessions — conteneurs redémarrés, connexions coupées. Appeler session_list avant d'exécuter.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "deployment_id"
  ],
  "properties": {
    "deployment_id": {
      "type": "string"
    }
  }
}
```

## `devpod__compose_service_logs`

- **Scope** : `read`
- **Description** : Retourne les logs d'un déploiement compose. Impact: read-only — aucune mutation.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "deployment_id"
  ],
  "properties": {
    "deployment_id": {
      "type": "string"
    },
    "service": {
      "type": "string",
      "description": "Nom d'un service spécifique (optionnel)."
    },
    "tail": {
      "type": "integer",
      "default": 200,
      "minimum": 1
    }
  }
}
```

## `devpod__compose_service_status`

- **Scope** : `read`
- **Description** : Rafraîchit et retourne le statut live d'un déploiement. Impact: read-only — aucune mutation.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "deployment_id"
  ],
  "properties": {
    "deployment_id": {
      "type": "string"
    }
  }
}
```

## `devpod__compose_service_down`

- **Scope** : `exec`
- **Description** : Détruit un déploiement (docker compose down -v + nettoyage). Irréversible : confirm doit valoir true. Impact: destructive-data — docker compose down -v : conteneurs + volumes supprimés, données perdues définitivement.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "deployment_id",
    "confirm"
  ],
  "properties": {
    "deployment_id": {
      "type": "string"
    },
    "confirm": {
      "type": "boolean",
      "description": "Doit valoir true (garde anti-suppression)."
    }
  }
}
```

## `devpod__workspace_messages`

- **Scope** : `read`
- **Description** : Liste les messages contextuels du workspace : machines de test disponibles, services docker-compose démarrés (ports, alias SSH, etc.). À lire en début de session pour connaître l'environnement de travail. Impact: read-only — aucune mutation.
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
      "description": "Nom du workspace dont on veut lire les messages."
    },
    "workspace_name": {
      "type": "string",
      "description": "Déprécié — utiliser 'workspace'."
    },
    "limit": {
      "type": "integer",
      "description": "Nombre max de messages retournés (1-500, défaut 50).",
      "default": 50
    }
  }
}
```

## `devpod__logs_query`

- **Scope** : `read`
- **Description** : Interroge les logs centralisés de la stack (tous les hosts + workspaces + système). Filtres structurés par host/role/project/service/unit/level, ou expression LogQL brute pour les cas avancés. Retourne les lignes correspondantes et un lien Grafana pré-filtré. Préférer cet outil à workspace_logs/compose_service_logs pour une vue transverse ou historique ; les outils par-conteneur restent utiles pour du point-in-time sur une cible. Impact: read-only — aucune mutation, simple lecture de l'agrégateur Loki.
- **Schéma d'entrée** :

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "query": {
      "type": "string",
      "description": "Expression LogQL brute (échappatoire puissance). Si fournie, prime sur les filtres."
    },
    "host": {
      "type": "string",
      "description": "Filtre label 'host'."
    },
    "role": {
      "type": "string",
      "description": "Filtre label 'role' (portail/workspace/test)."
    },
    "project": {
      "type": "string",
      "description": "Filtre label 'compose_project' (workspace ou déploiement compose)."
    },
    "service": {
      "type": "string",
      "description": "Filtre label 'compose_service'."
    },
    "unit": {
      "type": "string",
      "description": "Filtre label 'unit' (logs journald, ex. 'docker.service')."
    },
    "level": {
      "type": "string",
      "description": "Filtre niveau structlog via '| json | level=\"...\"'."
    },
    "since": {
      "type": "string",
      "default": "1h",
      "description": "Fenêtre relative (15m, 6h, 2d). Ignoré si start/end fournis."
    },
    "start": {
      "type": "string",
      "description": "Borne absolue de début (RFC 3339). Optionnelle."
    },
    "end": {
      "type": "string",
      "description": "Borne absolue de fin (RFC 3339). Optionnelle."
    },
    "limit": {
      "type": "integer",
      "default": 200,
      "minimum": 1,
      "maximum": 5000,
      "description": "Nombre max de lignes retournées."
    },
    "direction": {
      "type": "string",
      "enum": [
        "forward",
        "backward"
      ],
      "default": "backward",
      "description": "Ordre (backward = plus récent d'abord)."
    }
  }
}
```
