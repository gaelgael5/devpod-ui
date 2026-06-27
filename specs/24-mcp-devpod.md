# SPEC — MCP `devpod` : pilotage des workspaces de développement

> **Statut** : cadrage validé, prêt pour implémentation
> **Backend fédéré** : `devpod` (gateway `wrk.yoops.org/channels/`, pattern `backend_id__tool_name`)
> **Périmètre** : pilotage des workspaces conteneurisés et de leurs sessions d'agent depuis Claude web, via la passerelle.

---

## 1. Contexte et intention

L'acteur central est **le client conversationnel** (Claude web aujourd'hui), pas les agents qui tournent dans les workspaces. Le loop visé :

> cadrage conversationnel → dépôt du cadrage dans `agflow-doc` → indexation `agflow-rag` → récupération et travail par l'agent du workspace.

Les primitives décrites ici couvrent **le pilotage des workspaces** (famille `workspace_*` / `session_*` / `portal_*`). Les familles `doc__*` et `rag__*` font l'objet de specs distinctes.

**Exigence d'agnosticisme.** L'agent exécuté dans un workspace est interchangeable (`claude`, `codex`, `aider`, REPL…). Aucune primitive ne doit dépendre d'un agent particulier. Le choix de l'agent se fait à l'ouverture de session (`session_open.command`), jamais dans `send` / `capture` / `exec`.

---

## 2. Topologie

```
Hôte A : PORTAIL          (façade, CA propriétaire + mTLS, service interne)
            │  mTLS / enrollment (saut réseau A → B)
Hôte B : WORKSPACES       (conteneurs : rag, doc… — tmux + agent)
            │  SSH par certificat (établi à l'installation)
VM de test : moteur Docker (cibles pilotées par l'agent du conteneur)
```

Portail et workspaces sont sur des **hôtes distincts** : tout transit franchit le réseau. Le portail détient déjà les liens mTLS cross-host ; le MCP s'appuie dessus et ne traverse jamais d'hôte lui-même.

---

## 3. Invariants de conception (arbitrages actés)

| # | Invariant | Conséquence |
|---|-----------|-------------|
| I-1 | **Façade portail.** Le MCP appelle le service interne du portail. Il n'est *jamais* un client SSH/tmux autonome. | Le saut réseau A→B et le mTLS sont portés par le portail. Point d'audit unique. |
| I-2 | **Retour de session agnostique.** La lecture de sortie d'agent se fait via `capture-pane` (buffer terminal brut, ANSI). | Aucun couplage au format de log d'un agent donné. |
| I-3 | **Sessions sans état côté MCP.** Aucune notion de « connexion » ni de « session courante » implicite. La persistance est portée par **tmux** dans le conteneur. | Chaque primitive `session_*` prend un paramètre `session` explicite. |
| I-4 | **`get` ≠ `capture`.** `session_get` rend les **métadonnées** de session ; `session_capture` rend le **buffer brut** du pane. Pas de recouvrement. | Deux objets de retour distincts. |
| I-5 | **Confinement des chemins.** Tout chemin est relatif à la racine du workspace `/workspaces/{name}`, normalisé côté portail. Rejet de `..` et des chemins absolus ; un chemin résolu hors racine est refusé. | S'applique à `tree`, `read_file`, `mkdir`, `write_file`. |
| I-6 | **Écriture atomique.** `write_file` écrit en fichier temporaire puis effectue un `rename` atomique dans le répertoire cible. | Un fichier apparaît complet ou pas du tout (protège le pattern `write_file` → `session_send`). |
| I-7 | **Garde-fous récursion réservés.** Les champs `_origin` / `_depth` sont présents dans `session_send` mais **non câblés** en v1. | Permet d'activer la récursion agent→agent plus tard sans migration de schéma. |

---

## 4. Modèle d'autorisation

Chaque primitive porte un **scope** consommé par la couche d'autorisation du portail (raisonnement par scope, pas par nom de tool).

| Scope | Sémantique |
|-------|------------|
| `read` | lecture seule, sans effet de bord |
| `write` | modification du système de fichiers du workspace |
| `exec` | exécution de code / injection d'entrée dans un process |
| `admin` | cycle de vie conteneur / portail |

---

## 5. Contrat des primitives (format tool natif MCP)

Les noms ci-dessous sont **locaux** ; fédérés, ils deviennent `devpod__<nom>` (ex. `devpod__workspace_list`).

### 5.1 Famille `workspace_*`

#### `workspace_list` — `scope: read`
Liste les workspaces connus du portail.
```json
{
  "name": "workspace_list",
  "description": "Liste les workspaces avec leur statut, node et recette.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "status": {
        "type": "string",
        "enum": ["running", "stopped", "all"],
        "default": "all",
        "description": "Filtre optionnel sur le statut."
      }
    }
  }
}
```
**Retour** : `[{ id, name, repo, status, node, recipe, tags[] }]`

#### `workspace_status` — `scope: read`
État détaillé d'un workspace.
```json
{
  "name": "workspace_status",
  "description": "Retourne l'état de santé d'un workspace : conteneur et agent.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["workspace"],
    "properties": {
      "workspace": { "type": "string", "description": "Nom du workspace." }
    }
  }
}
```
**Retour** : `{ workspace, health, container_up, agent_up }`
> *Backlog* : champ `link_state` (`connected` / `stale` / `lost`) ajouté avec `portal_reload` modèle (b).

#### `workspace_start` / `workspace_stop` / `workspace_restart` — `scope: admin`
Cycle de vie du conteneur. Signature identique pour les trois.
```json
{
  "name": "workspace_start",
  "description": "Démarre le conteneur du workspace. (idem stop / restart)",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["workspace"],
    "properties": {
      "workspace": { "type": "string" }
    }
  }
}
```
**Retour** : `{ workspace, status }`

#### `workspace_tree` — `scope: read`
Arborescence du workspace. `depth` et `ignore` par défaut **obligatoires** pour ne pas exploser le contexte.
```json
{
  "name": "workspace_tree",
  "description": "Liste l'arborescence du workspace à partir d'un chemin, avec profondeur et exclusions.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["workspace"],
    "properties": {
      "workspace": { "type": "string" },
      "path": { "type": "string", "default": ".", "description": "Chemin relatif à la racine du workspace (I-5)." },
      "depth": { "type": "integer", "default": 2, "minimum": 1 },
      "ignore": {
        "type": "array",
        "items": { "type": "string" },
        "default": [".git", ".venv", "node_modules", "__pycache__"]
      }
    }
  }
}
```
**Retour** : arborescence imbriquée `{ name, type: "file"|"dir", children?[] }`

#### `workspace_read_file` — `scope: read`
```json
{
  "name": "workspace_read_file",
  "description": "Lit le contenu d'un fichier du workspace.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["workspace", "path"],
    "properties": {
      "workspace": { "type": "string" },
      "path": { "type": "string", "description": "Chemin relatif à la racine (I-5)." }
    }
  }
}
```
**Retour** : `{ path, content, size, sha256 }`

#### `workspace_mkdir` — `scope: write`
```json
{
  "name": "workspace_mkdir",
  "description": "Crée un répertoire (et ses parents) dans le workspace.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["workspace", "path"],
    "properties": {
      "workspace": { "type": "string" },
      "path": { "type": "string", "description": "Chemin relatif à la racine (I-5)." }
    }
  }
}
```
**Retour** : `{ path }`

#### `workspace_write_file` — `scope: write`
Écriture atomique (I-6).
```json
{
  "name": "workspace_write_file",
  "description": "Écrit un fichier dans le workspace de façon atomique (tempfile + rename).",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["workspace", "path", "content"],
    "properties": {
      "workspace": { "type": "string" },
      "path": { "type": "string", "description": "Chemin relatif à la racine (I-5)." },
      "content": { "type": "string" },
      "create_dirs": { "type": "boolean", "default": true, "description": "Crée les répertoires parents manquants." }
    }
  }
}
```
**Retour** : `{ path, sha256, bytes }`
> *Backlog* : paramètre optionnel `expected_sha256` (garde optimiste, cf. §7).

#### `workspace_exec` — `scope: exec`
Commande **one-shot, non-interactive** : un shell neuf, exécution, sortie propre, fin. Canal **distinct** du tmux de l'agent (ne pollue pas la session interactive). S'exécute dans le contexte du conteneur du workspace (cwd par défaut = racine du workspace, même environnement que l'agent).
```json
{
  "name": "workspace_exec",
  "description": "Exécute une commande non-interactive dans le conteneur du workspace et retourne sa sortie.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["workspace", "command"],
    "properties": {
      "workspace": { "type": "string" },
      "command": { "type": "string", "description": "Commande shell à exécuter." },
      "cwd": { "type": "string", "description": "Répertoire de travail relatif à la racine (défaut : racine du workspace)." },
      "timeout_s": { "type": "integer", "default": 60, "minimum": 1 }
    }
  }
}
```
**Retour** : `{ stdout, stderr, exit_code }`

---

### 5.2 Famille `session_*`

Sessions persistantes portées par **tmux**, adressées explicitement (I-3). Distinction clé avec `workspace_exec` : ici le texte est de l'**entrée** pour un process **déjà vivant** qui accumule de l'état (l'agent), pas une commande éphémère.

#### `session_open` — `scope: exec`
Crée (idempotent) une session tmux nommée et y lance la commande agent. **Point unique où l'agnosticisme s'exprime.**
```json
{
  "name": "session_open",
  "description": "Ouvre (idempotent) une session tmux nommée et y lance une commande agent.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["workspace", "command"],
    "properties": {
      "workspace": { "type": "string" },
      "command": { "type": "string", "description": "Commande lançant l'agent (ex. 'claude', 'codex', 'aider'). Agnostique." },
      "name": { "type": "string", "default": "main", "description": "Nom de la session tmux." },
      "cwd": { "type": "string", "description": "Répertoire de travail relatif à la racine." }
    }
  }
}
```
**Retour** : `{ session_id, workspace, name, command }`

#### `session_send` — `scope: exec`
Injecte du texte dans le stdin du process au premier plan de la session (`tmux send-keys`). `submit=false` permet de stager un prompt sans le valider (composition multi-ligne / main rendue avant envoi).
```json
{
  "name": "session_send",
  "description": "Envoie du texte vers le stdin de l'agent d'une session (send-keys). N'attend pas de sortie : lire via session_capture.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["workspace", "text"],
    "properties": {
      "workspace": { "type": "string" },
      "session": { "type": "string", "default": "main" },
      "text": { "type": "string" },
      "submit": { "type": "boolean", "default": true, "description": "Si true, valide l'entrée (Enter). Si false, stage sans valider." },
      "_origin": { "type": "string", "description": "RÉSERVÉ (I-7) — origine de la tâche pour la récursion future. Non câblé en v1." },
      "_depth": { "type": "integer", "description": "RÉSERVÉ (I-7) — profondeur de récursion. Non câblé en v1." }
    }
  }
}
```
**Retour** : `{ sent: true }`

#### `session_capture` — `scope: read`
Rend le **buffer brut** du pane (I-2, I-4), tel que l'œil le verrait (codes ANSI inclus).
```json
{
  "name": "session_capture",
  "description": "Capture le buffer brut du pane d'une session (capture-pane).",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["workspace"],
    "properties": {
      "workspace": { "type": "string" },
      "session": { "type": "string", "default": "main" },
      "lines": { "type": "integer", "default": 200, "minimum": 1, "description": "Nombre de lignes à remonter." }
    }
  }
}
```
**Retour** : `{ output }`

#### `session_list` — `scope: read`
```json
{
  "name": "session_list",
  "description": "Liste les sessions actives d'un workspace.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["workspace"],
    "properties": {
      "workspace": { "type": "string" }
    }
  }
}
```
**Retour** : `[{ session_id, name, command, alive }]`

#### `session_get` — `scope: read`
Métadonnées de session (I-4), distinctes du buffer.
```json
{
  "name": "session_get",
  "description": "Retourne les métadonnées d'une session (nom, commande, état, pane, uptime).",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["workspace"],
    "properties": {
      "workspace": { "type": "string" },
      "session": { "type": "string", "default": "main" }
    }
  }
}
```
**Retour** : `{ session_id, name, command, alive, pane_id, uptime_s }`

---

### 5.3 Famille `portal_*`

#### `portal_reload` — `scope: admin`
Reconnecte le portail à un workspace nommé après une mise à jour du portail (le conteneur, lui, n'a pas été interrompu). Modèle **(a)** : reconnexion forcée du workspace ciblé.
```json
{
  "name": "portal_reload",
  "description": "Reconnecte le portail à un workspace dont le conteneur tourne déjà (post mise à jour du portail).",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["workspace"],
    "properties": {
      "workspace": { "type": "string" }
    }
  }
}
```
**Retour** : `{ workspace, reconnected: true }`

---

## 6. Exigence de documentation produit

**Le contrat de ce MCP doit être exposé dans la documentation du produit.** Chaque primitive (nom fédéré, description, schéma d'entrée, retour, scope) est publiée et tenue à jour dans la doc du portail, comme source de référence unique pour les intégrateurs et les agents consommateurs. La documentation et le contrat implémenté ne doivent pas diverger : toute évolution de signature passe d'abord par la mise à jour de la spec et de la doc.

---

## 7. Backlog (conçu / noté, non câblé)

| Sujet | Origine | Note |
|-------|---------|------|
| `workspace_write_file.expected_sha256` | arbitrage 6 | Garde optimiste (échec si le fichier a changé depuis le `read`). Aligné sur la concurrence optimiste de docflow. |
| `portal_reload` modèle (b) | reload | Réconciliation pilotée par `link_state` exposé dans `workspace_status` ; fondation de l'automatisation future. |
| Récursion agent→agent | garde-fous | Câblage de `_origin` / `_depth` + limite de profondeur propagée. Schéma déjà réservé (I-7). |
| Retour de session structuré v2 | arbitrage 2 | Convention de statut agnostique côté workspace, au-delà du `capture-pane` ANSI. |
| Pilotage direct de la VM de test par le portail | topologie | Aujourd'hui hors scope : la VM (moteur Docker) est pilotée par l'agent du conteneur via SSH par certificat. À ouvrir seulement si le besoin passe du conteneur au portail. |
| Réseau / ports des tests d'intégration (`-p`) | feature browserless | Frontière de visibilité des ports (VM / conteneur / portail) à traiter avec la feature de tests d'intégration. |
