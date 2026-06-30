# MCP devpod — Référence complète des méthodes

> Backend fédéré : `devpod` — noms fédérés : `devpod__<nom>` (ex. `devpod__workspace_list`)
> Gateway de test : `http://192.168.10.173:8080/mcp/` — auth : `Authorization: Bearer mcpk_...`
> Specs de référence : `specs/24-mcp-devpod.md`, `specs/25-mcp-devpod-complement.md`, `specs/23-mcp-gateway.md`
>
> **Statut des tests** : ✅ ok | ⬜ non testé | ❌ KO

---

## Modèle d'impact (légende)

| Tag | Sémantique |
|-----|-----------|
| `read-only` | Lecture seule, aucun effet de bord |
| `write-safe` | Modification de fichiers/config ; conteneur non redémarré |
| `non-destructive` | Création ou idempotent ; n'affecte pas l'existant |
| `destructive-sessions` | Sessions SSH/tmux coupées, travail en cours perdu |
| `destructive-data` | Données supprimées définitivement (irréversible) |

## Modèle de scope

| Scope | Sémantique |
|-------|-----------|
| `read` | Lecture seule |
| `write` | Modification filesystem workspace |
| `exec` | Exécution de code / injection stdin |
| `admin` | Cycle de vie conteneur / portail |

---

## Famille `workspace_*`

### `workspace_list` — `scope: read` — `read-only`
Liste les workspaces avec leur statut, node et recette.

**Paramètres :**
| Champ | Type | Requis | Défaut | Description |
|-------|------|--------|--------|-------------|
| `status` | enum | non | `"all"` | `"running"` \| `"stopped"` \| `"all"` |

**Retour :** `[{ id, name, status, node, recipe }]`

---

### `workspace_get` — `scope: read` — `read-only`
Descripteur complet d'un workspace (repo, branche, recette, node, sessions, dates).

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `workspace` | string | oui | Nom du workspace |

**Retour :** `{ id, name, repo, branch, status, node, recipe, tags[], devcontainer_ref, sessions[], created_at }`

---

### `workspace_status` — `scope: read` — `read-only`
État de santé d'un workspace : conteneur et agent.

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `workspace` | string | oui | Nom du workspace |

**Retour :** `{ container_status, agent_status, ... }`

---

### `workspace_create` — `scope: admin` — `non-destructive` — *long-running async*
Crée un workspace depuis un repo et une recette. Retourne immédiatement un `operation_id`.

**Paramètres :**
| Champ | Type | Requis | Défaut | Description |
|-------|------|--------|--------|-------------|
| `name` | string | oui | — | Nom du workspace |
| `repo` | string | oui | — | URL du dépôt git |
| `branch` | string | non | `"dev"` | Branche cible |
| `recipe` | string | non | auto | Recette (Dev Container Features) |
| `node` | string | non | auto | Node cible (placement auto sinon) |

**Retour :** `{ operation_id }`

---

### `workspace_delete` — `scope: admin` — `destructive-data`
Supprime un workspace et son conteneur. Irréversible.

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `workspace` | string | oui | Nom du workspace |
| `confirm` | boolean | oui | Doit valoir `true` (garde anti-suppression) |

**Retour :** `{ operation_id }` ou `{ workspace, deleted: true }`

---

### `workspace_stop` — `scope: admin` — `destructive-sessions` — *async*
Arrête le conteneur du workspace. Sessions SSH/tmux coupées.

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `workspace` | string | oui | Nom du workspace |

**Retour :** `{ operation_id }`

---

### `workspace_restart` — `scope: admin` — `destructive-sessions` — *async*
Redémarre le conteneur (stop + devpod up). Sessions SSH/tmux coupées.

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `workspace` | string | oui | Nom du workspace |

**Retour :** `{ operation_id }`

---

### `workspace_reconnect` — `scope: admin` — `non-destructive` — *async*
Reconnecte le workspace au portail (devpod up idempotent). Si le conteneur tourne déjà, rétablit le tunnel sans le recréer.

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `workspace` | string | oui | Nom du workspace |

**Retour :** `{ operation_id }`

---

### `workspace_apply_recipe` — `scope: admin` — `destructive-sessions` — *async*
Applique/met à jour une recette sur un workspace existant. Implique une recréation complète du conteneur.

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `workspace` | string | oui | Nom du workspace |
| `recipe` | string | oui | Identifiant de la recette |

**Retour :** `{ operation_id }`

---

### `workspace_logs` — `scope: read` — `read-only`
Logs d'un workspace par source (setup, agent, conteneur).

**Paramètres :**
| Champ | Type | Requis | Défaut | Description |
|-------|------|--------|--------|-------------|
| `workspace` | string | oui | — | Nom du workspace |
| `source` | enum | non | `"container"` | `"setup"` \| `"agent"` \| `"container"` |
| `lines` | integer | non | `200` | Nombre de lignes (min 1) |
| `since` | string | non | — | Réservé v1 (non appliqué) |

**Retour :** `{ source, output }`

---

### `workspace_resources` — `scope: read` — `read-only`
Consommation CPU / mémoire / disque du conteneur.

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `workspace` | string | oui | Nom du workspace |

**Retour :** `{ cpu_pct, mem_used, mem_limit, disk_used, disk_limit }`

---

### `workspace_exec` — `scope: exec` — `write-safe`
Exécute une commande non-interactive dans le conteneur et retourne sa sortie.

**Paramètres :**
| Champ | Type | Requis | Défaut | Description |
|-------|------|--------|--------|-------------|
| `workspace` | string | oui | — | Nom du workspace |
| `command` | string | oui | — | Commande shell à exécuter |
| `cwd` | string | non | racine | Répertoire de travail relatif à la racine |
| `timeout_s` | integer | non | `60` | Timeout en secondes (min 1) |

**Retour :** `{ stdout, stderr, exit_code }`

---

### `workspace_tree` — `scope: read` — `read-only`
Arborescence du workspace à partir d'un chemin.

**Paramètres :**
| Champ | Type | Requis | Défaut | Description |
|-------|------|--------|--------|-------------|
| `workspace` | string | oui | — | Nom du workspace |
| `path` | string | non | `"."` | Chemin relatif à la racine |
| `depth` | integer | non | `2` | Profondeur (min 1) |
| `ignore` | array | non | `[".git", ".venv", "node_modules", "__pycache__"]` | Patterns à exclure |

**Retour :** arborescence en texte

---

### `workspace_read_file` — `scope: read` — `read-only`
Lit le contenu d'un fichier du workspace.

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `workspace` | string | oui | Nom du workspace |
| `path` | string | oui | Chemin relatif à la racine (I-5) |

**Retour :** `{ content }`

---

### `workspace_write_file` — `scope: write` — `write-safe`
Écrit un fichier dans le workspace de façon atomique (tempfile + rename).

**Paramètres :**
| Champ | Type | Requis | Défaut | Description |
|-------|------|--------|--------|-------------|
| `workspace` | string | oui | — | Nom du workspace |
| `path` | string | oui | — | Chemin relatif à la racine (I-5) |
| `content` | string | oui | — | Contenu du fichier |
| `create_dirs` | boolean | non | `true` | Crée les répertoires parents manquants |

**Retour :** `{ path, written: true }`

---

### `workspace_mkdir` — `scope: write` — `write-safe`
Crée un répertoire (et ses parents) dans le workspace.

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `workspace` | string | oui | Nom du workspace |
| `path` | string | oui | Chemin relatif à la racine (I-5) |

**Retour :** `{ path, created: true }`

---

### `workspace_messages` — `scope: read` — `read-only`
Messages contextuels du workspace : machines de test disponibles, services docker-compose démarrés, ports, alias SSH. À lire en début de session.

**Paramètres :**
| Champ | Type | Requis | Défaut | Description |
|-------|------|--------|--------|-------------|
| `workspace_name` | string | oui | — | Nom du workspace |
| `limit` | integer | non | `50` | Nombre max de messages (1-500) |

**Retour :** `[{ type, content, ... }]`

---

### `workspace_git_status` — `scope: read` — `read-only`
État git du workspace (branche, fichiers modifiés, diff optionnel).

**Paramètres :**
| Champ | Type | Requis | Défaut | Description |
|-------|------|--------|--------|-------------|
| `workspace` | string | oui | — | Nom du workspace |
| `with_diff` | boolean | non | `false` | Inclure le diff |

**Retour :** `{ branch, staged[], unstaged[], untracked[], diff? }`

---

### `workspace_git_commit` — `scope: exec` — `write-safe`
Commit conventionnel sur la branche dev (garde de branche). Push optionnel.
> Refuse si la branche courante n'est pas `dev`.

**Paramètres :**
| Champ | Type | Requis | Défaut | Description |
|-------|------|--------|--------|-------------|
| `workspace` | string | oui | — | Nom du workspace |
| `message` | string | oui | — | Message commit conventionnel FR (ex. `feat: ...`) |
| `files` | array | non | tout tracked modifié | Fichiers à stager |
| `push` | boolean | non | `false` | Push après commit |

**Retour :** `{ commit_sha, branch, pushed }`

---

### `workspace_profile_set` — `scope: admin` — `destructive-sessions`
Applique un profil VS Code (extensions et réglages Open VSX). Implique une recréation complète du conteneur.

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `workspace` | string | oui | Nom du workspace |
| `profile` | string | oui | Identifiant du profil VS Code |

**Retour :** `{ profile, applied: true }`

---

### `workspace_secrets_list` — `scope: read` — `read-only`
Liste les références de secrets (`${vault://...}`) liées au workspace. **Noms uniquement, jamais de valeurs.**

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `workspace` | string | oui | Nom du workspace |

**Retour :** `[{ reference, target }]` — noms uniquement

---

### `workspace_secrets_bind` — `scope: write` — `write-safe`
Lie une référence `${vault://...}` à une variable d'environnement cible. La résolution reste interne au runtime ; **aucune valeur n'est retournée** (principe zéro-knowledge Harpocrate).

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `workspace` | string | oui | Nom du workspace |
| `reference` | string | oui | Référence vault, ex. `${vault://bloc/nom}` |
| `target` | string | oui | Variable d'environnement cible |

**Retour :** `{ target, bound: true }` — jamais la valeur résolue

---

## Famille `session_*`

### `session_list` — `scope: read` — `read-only`
Liste les sessions tmux actives d'un workspace.

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `workspace` | string | oui | Nom du workspace |

**Retour :** `[{ name, command, state, uptime }]`

---

### `session_get` — `scope: read` — `read-only`
Métadonnées d'une session (nom, commande, état, pane, uptime).

**Paramètres :**
| Champ | Type | Requis | Défaut | Description |
|-------|------|--------|--------|-------------|
| `workspace` | string | oui | — | Nom du workspace |
| `session` | string | non | `"main"` | Nom de la session tmux |

**Retour :** `{ name, command, state, pane, uptime }`

---

### `session_open` — `scope: exec` — `non-destructive`
Ouvre (idempotent) une session tmux nommée et y lance une commande agent.

**Paramètres :**
| Champ | Type | Requis | Défaut | Description |
|-------|------|--------|--------|-------------|
| `workspace` | string | oui | — | Nom du workspace |
| `command` | string | oui | — | Commande agent (ex. `claude`, `codex`) |
| `name` | string | non | `"main"` | Nom de la session tmux |
| `cwd` | string | non | racine | Répertoire de travail relatif |

**Retour :** `{ session, created }`

---

### `session_close` — `scope: exec` — `non-destructive` (pour le workspace)
Termine une session tmux nommée et le process qu'elle héberge. Le conteneur reste en cours.

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `workspace` | string | oui | Nom du workspace |
| `session` | string | oui | Nom de la session tmux |

**Retour :** `{ closed: true }`

---

### `session_send` — `scope: exec` — `non-destructive`
Envoie du texte vers le stdin de l'agent d'une session (send-keys). N'attend pas de sortie : lire via `session_capture`.

**Paramètres :**
| Champ | Type | Requis | Défaut | Description |
|-------|------|--------|--------|-------------|
| `workspace` | string | oui | — | Nom du workspace |
| `text` | string | oui | — | Texte à envoyer |
| `session` | string | non | `"main"` | Nom de la session |
| `submit` | boolean | non | `true` | Valide l'entrée (Enter) si true |
| `_origin` | string | non | — | RÉSERVÉ (I-7) — non câblé v1 |
| `_depth` | integer | non | — | RÉSERVÉ (I-7) — non câblé v1 |

**Retour :** `{ sent: true }`

---

### `session_capture` — `scope: read` — `read-only`
Capture le buffer brut du pane d'une session (capture-pane, ANSI).

**Paramètres :**
| Champ | Type | Requis | Défaut | Description |
|-------|------|--------|--------|-------------|
| `workspace` | string | oui | — | Nom du workspace |
| `session` | string | non | `"main"` | Nom de la session |
| `lines` | integer | non | `200` | Nombre de lignes à remonter (min 1) |

**Retour :** `{ output }` (buffer brut ANSI)

---

### `session_interrupt` — `scope: exec` — `non-destructive`
Envoie un signal d'interruption (Ctrl-C) au process au premier plan d'une session.

**Paramètres :**
| Champ | Type | Requis | Défaut | Description |
|-------|------|--------|--------|-------------|
| `workspace` | string | oui | — | Nom du workspace |
| `session` | string | non | `"main"` | Nom de la session |

**Retour :** `{ interrupted: true }`

---

## Famille `operations_*`

### `operations_get` — `scope: read` — `read-only`
État, progression et résultat d'une opération asynchrone.

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `operation_id` | string | oui | ID d'opération retourné par un tool async |

**Retour :** `{ operation_id, kind, workspace, state: "pending"|"running"|"done"|"failed", progress, result?, error? }`

---

### `operations_list` — `scope: read` — `read-only`
Liste les opérations en cours, filtrables par workspace.

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `workspace` | string | non | Filtre optionnel |

**Retour :** `[{ operation_id, kind, workspace, state, progress }]`

---

## Famille `node_*`

### `node_list` — `scope: read` — `read-only`
Liste les nodes enrôlés (hôtes mTLS) et leur disponibilité.

**Paramètres :** aucun

**Retour :** `[{ node_id, name, host, status, capacity }]`

---

## Famille `compose_service_*`

### `compose_service_list` — `scope: read` — `read-only`
Liste les déploiements compose de l'utilisateur.

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `node_id` | string | non | Filtre optionnel sur le nœud |

**Retour :** `[{ deployment_id, template_id, name, node_id, status }]`

---

### `compose_service_start` — `scope: admin` — `non-destructive`
Démarre un template docker-compose sur une machine de test. Les ports alias sont alloués automatiquement.

**Paramètres :**
| Champ | Type | Requis | Défaut | Description |
|-------|------|--------|--------|-------------|
| `template_id` | string | oui | — | ID du template |
| `node_id` | string | oui | — | ID du nœud cible (`node_list`) |
| `name` | string | oui | — | Slug du déploiement |
| `env_values` | object | non | `{}` | Valeurs des paramètres non-port |

**Retour :** `{ deployment_id, ports, ... }`

---

### `compose_service_stop` — `scope: admin` — `destructive-sessions`
Arrête les conteneurs d'un déploiement (docker compose stop). Volumes conservés.

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `deployment_id` | string | oui | ID du déploiement |

**Retour :** `{ stopped: true }`

---

### `compose_service_restart` — `scope: admin` — `destructive-sessions`
Redémarre les conteneurs d'un déploiement (docker compose restart).

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `deployment_id` | string | oui | ID du déploiement |

**Retour :** `{ restarted: true }`

---

### `compose_service_status` — `scope: read` — `read-only`
Statut live d'un déploiement.

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `deployment_id` | string | oui | ID du déploiement |

**Retour :** `{ deployment_id, status, services[], ... }`

---

### `compose_service_logs` — `scope: read` — `read-only`
Logs d'un déploiement compose.

**Paramètres :**
| Champ | Type | Requis | Défaut | Description |
|-------|------|--------|--------|-------------|
| `deployment_id` | string | oui | — | ID du déploiement |
| `service` | string | non | tous | Nom d'un service spécifique |
| `tail` | integer | non | `200` | Nombre de lignes (min 1) |

**Retour :** `{ output }`

---

### `compose_service_down` — `scope: admin` — `destructive-data`
Détruit un déploiement (docker compose down -v + nettoyage). Irréversible.

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `deployment_id` | string | oui | ID du déploiement |
| `confirm` | boolean | oui | Doit valoir `true` (garde anti-suppression) |

**Retour :** `{ destroyed: true }`

---

## Famille `compose_template_*`

### `compose_template_list` — `scope: read` — `read-only`
Liste les templates docker-compose disponibles.

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `tag` | string | non | Filtre optionnel sur un tag |

**Retour :** `[{ id, name, description, tags[], version }]`

---

### `compose_template_get` — `scope: read` — `read-only`
Descripteur complet d'un template (YAML inclus).

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `template_id` | string | oui | ID du template |

**Retour :** `{ id, name, description, compose_content, parameters[], tags[], version }`

---

### `compose_template_create` — `scope: admin` — `write-safe`
Crée un nouveau template dans la galerie. Le YAML est validé (ports codés en dur interdits, bind-mounts absolus interdits).

**Paramètres :**
| Champ | Type | Requis | Défaut | Description |
|-------|------|--------|--------|-------------|
| `id` | string | oui | — | Slug du template (`^[a-z0-9-]+$`) |
| `name` | string | oui | — | Nom affiché |
| `compose_content` | string | oui | — | Contenu YAML du docker-compose.yml |
| `description` | string | non | `""` | Description |
| `parameters` | array | non | `[]` | Paramètres (type string/number/bool/enum/secret) |
| `tags` | array | non | `[]` | Tags |
| `version` | string | non | `"1"` | Version |

**Retour :** `{ id, created: true }`

---

### `compose_template_update` — `scope: admin` — `write-safe`
Met à jour un template existant. Seuls les champs fournis sont modifiés (`compose_content` requis).

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `id` | string | oui | ID du template |
| `compose_content` | string | oui | Nouveau contenu YAML |
| `name` | string | non | Nouveau nom |
| `description` | string | non | Nouvelle description |
| `parameters` | array | non | Nouveaux paramètres |
| `tags` | array | non | Nouveaux tags |
| `version` | string | non | Nouvelle version |

**Retour :** `{ id, updated: true }`

---

## Famille `portal_*`

### `portal_reload` — `scope: admin` — `non-destructive`
Reconnecte le portail à un workspace dont le conteneur tourne déjà (post mise à jour du portail). Refusé si le conteneur est arrêté.

**Paramètres :**
| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `workspace` | string | oui | Nom du workspace |

**Retour :** `{ reconnected: true }` ou `{ reason: "container_down" }`

---

## Famille `gateway_*`

### `gateway__list_backends` — `read-only`
Liste les backends MCP fédérés accessibles et leur disponibilité.

**Paramètres :** aucun

**Retour :** `[{ backend_id, name, status, tools_count }]`

---

## Tableau récapitulatif

| Méthode | Scope | Impact | Long-running |
|---------|-------|--------|:---:|
| `workspace_list` ✅ | read | read-only | — |
| `workspace_get` ❌ | read | read-only | — |
| `workspace_status` | read | read-only | — |
| `workspace_create` | admin | non-destructive | ✓ |
| `workspace_delete` | admin | destructive-data | ✓ |
| `workspace_stop` | admin | destructive-sessions | ✓ |
| `workspace_restart` | admin | destructive-sessions | ✓ |
| `workspace_reconnect` | admin | non-destructive | ✓ |
| `workspace_apply_recipe` | admin | destructive-sessions | ✓ |
| `workspace_logs` | read | read-only | — |
| `workspace_resources` | read | read-only | — |
| `workspace_exec` | exec | write-safe | — |
| `workspace_tree` | read | read-only | — |
| `workspace_read_file` | read | read-only | — |
| `workspace_write_file` | write | write-safe | — |
| `workspace_mkdir` | write | write-safe | — |
| `workspace_messages` | read | read-only | — |
| `workspace_git_status` | read | read-only | — |
| `workspace_git_commit` | exec | write-safe | — |
| `workspace_profile_set` | admin | destructive-sessions | ✓ |
| `workspace_secrets_list` | read | read-only | — |
| `workspace_secrets_bind` | write | write-safe | — |
| `session_list` | read | read-only | — |
| `session_get` | read | read-only | — |
| `session_open` | exec | non-destructive | — |
| `session_close` | exec | non-destructive | — |
| `session_send` | exec | non-destructive | — |
| `session_capture` | read | read-only | — |
| `session_interrupt` | exec | non-destructive | — |
| `operations_get` | read | read-only | — |
| `operations_list` | read | read-only | — |
| `node_list` | read | read-only | — |
| `compose_service_list` | read | read-only | — |
| `compose_service_start` | admin | non-destructive | — |
| `compose_service_stop` | admin | destructive-sessions | — |
| `compose_service_restart` | admin | destructive-sessions | — |
| `compose_service_status` | read | read-only | — |
| `compose_service_logs` | read | read-only | — |
| `compose_service_down` | admin | destructive-data | — |
| `compose_template_list` | read | read-only | — |
| `compose_template_get` | read | read-only | — |
| `compose_template_create` | admin | write-safe | — |
| `compose_template_update` | admin | write-safe | — |
| `portal_reload` | admin | non-destructive | — |
| `gateway__list_backends` | — | read-only | — |

**Total : 45 méthodes**
