# SPEC — MCP `devpod` : complément (reliqua de la surface de pilotage)

> **Statut** : complément du contrat prioritaire (`SPEC-mcp-devpod.md`).
> **Lecture** : ce document couvre les fonctions de pilotage *non retenues* dans la liste prioritaire. Il reprend les invariants I-1 à I-7 et le modèle de scopes du contrat principal.
> **Hors périmètre** : familles `doc__*` et `rag__*` (specs dédiées).
>
> Les primitives sont classées en trois sections selon leur niveau de décision :
> - **A — Façades propres** : directement spécifiables, aucun arbitrage résiduel.
> - **B — À arbitrer** : émises en version provisoire, dépendent d'une décision ouverte (signalée).
> - **C — Hors périmètre / autre track** : notées, non spécifiées ici.

---

## Décisions actées (2026-06-27)

> Tranchées avec l'architecte avant implémentation (à réaliser en session dédiée).

1. **Pattern long-running → `operations_*` (async) ADOPTÉ.** `workspace_create` / `delete` / `apply_recipe` lancent l'action et retournent `{ operation_id }` ; la famille `operations_get` / `operations_list` porte le suivi (un fichier d'état par opération dans le stockage YAML du portail). **Rétro-impact à traiter** : harmoniser `workspace_start` / `stop` / `restart` de la spec 24 (aujourd'hui synchrones) sur le même modèle async — étape du chantier 25.
2. **`agent_dispatch`** : recommandation **(a) abandon** par défaut (`session_send` + `session_capture` couvrent le besoin) ; n'activer la sur-couche **(b)** (dispatch = send + opération suivie) que si un besoin avéré de traquer des tâches agent longues émerge. À confirmer au démarrage de l'implémentation.
3. **`workspace_delete`** : flag **`confirm: true` suffisant** (garde minimal explicite ; l'appelant pouvant être un agent, le flag est le bon garde-fou). Pas de double validation.
4. **`workspace_secrets_*`** : conception **référence/injection validée** — `secrets_list` ne rend que des noms de références, `secrets_bind` lie une référence à une cible sans jamais restituer la valeur (résolution interne au runtime, zéro-knowledge Harpocrate préservé).

**Périmètre d'implémentation de la spec 25** : Section A (9 façades) + Section B avec les décisions ci-dessus (operations_* + create/delete/apply_recipe async + secrets référence/injection) + harmonisation async des lifecycle de la 24. Section C reste hors périmètre.

---

## Section A — Façades propres (spec-ready)

### `workspace_get` — `scope: read`
Descripteur complet d'un workspace. Distinct de `workspace_list` (résumé) et `workspace_status` (santé).
```json
{
  "name": "workspace_get",
  "description": "Retourne le descripteur complet d'un workspace (repo, branche, recette, node, sessions, dates).",
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
**Retour** : `{ id, name, repo, branch, status, node, recipe, tags[], devcontainer_ref, sessions[], created_at }`

### `workspace_logs` — `scope: read`
Logs d'un workspace, par source.
```json
{
  "name": "workspace_logs",
  "description": "Retourne les logs d'un workspace (setup d'installation, agent ou conteneur).",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["workspace"],
    "properties": {
      "workspace": { "type": "string" },
      "source": { "type": "string", "enum": ["setup", "agent", "container"], "default": "container" },
      "lines": { "type": "integer", "default": 200, "minimum": 1 },
      "since": { "type": "string", "description": "Filtre temporel optionnel (ISO 8601 ou durée type '10m')." }
    }
  }
}
```
**Retour** : `{ source, output }`

### `workspace_resources` — `scope: read`
Consommation du conteneur (utile en placement multi-node).
```json
{
  "name": "workspace_resources",
  "description": "Retourne la consommation CPU / mémoire / disque du conteneur du workspace.",
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
**Retour** : `{ cpu_pct, mem_used, mem_limit, disk_used, disk_limit }`

### `session_interrupt` — `scope: exec`
Interrompt la tâche en cours dans une session (équivalent Ctrl-C dans le pane). Complément naturel de `session_send` : permet de stopper un agent parti en vrille sans tuer la session.
```json
{
  "name": "session_interrupt",
  "description": "Envoie un signal d'interruption (Ctrl-C) au process au premier plan d'une session.",
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
**Retour** : `{ interrupted: true }`

### `session_close` — `scope: exec`
Bookend de cycle de vie manquant face à `session_open` : tue la session tmux nommée.
```json
{
  "name": "session_close",
  "description": "Termine une session tmux nommée et le process qu'elle héberge.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["workspace", "session"],
    "properties": {
      "workspace": { "type": "string" },
      "session": { "type": "string" }
    }
  }
}
```
**Retour** : `{ closed: true }`

### `workspace_git_status` — `scope: read`
Lecture de l'état git (status + diff). Lecture seule volontairement séparée du commit pour respecter le scope.
```json
{
  "name": "workspace_git_status",
  "description": "Retourne l'état git du workspace (branche, fichiers modifiés, diff optionnel).",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["workspace"],
    "properties": {
      "workspace": { "type": "string" },
      "with_diff": { "type": "boolean", "default": false }
    }
  }
}
```
**Retour** : `{ branch, staged[], unstaged[], untracked[], diff? }`

### `workspace_git_commit` — `scope: exec`
**Git gardé, pas git brut.** Le `workspace_exec` générique pourrait lancer n'importe quel git ; cette primitive encode les conventions : commit conventionnel FR, **branche `dev` obligatoire** (rejet sinon), push optionnel. C'est sa valeur ajoutée par rapport à `exec`.
```json
{
  "name": "workspace_git_commit",
  "description": "Commit conventionnel sur la branche dev (garde de branche). Push optionnel.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["workspace", "message"],
    "properties": {
      "workspace": { "type": "string" },
      "message": { "type": "string", "description": "Message au format commit conventionnel FR (ex. 'feat: ...')." },
      "files": {
        "type": "array",
        "items": { "type": "string" },
        "description": "Fichiers à stager (défaut : tout le tracked modifié)."
      },
      "push": { "type": "boolean", "default": false }
    }
  }
}
```
**Retour** : `{ commit_sha, branch, pushed }`
> Refuse si la branche courante n'est pas `dev`.

### `workspace_profile_set` — `scope: write`
Applique un profil VS Code (extensions / settings Open VSX).
```json
{
  "name": "workspace_profile_set",
  "description": "Applique un profil VS Code (extensions et réglages Open VSX) au workspace.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["workspace", "profile"],
    "properties": {
      "workspace": { "type": "string" },
      "profile": { "type": "string", "description": "Identifiant du profil VS Code défini côté portail." }
    }
  }
}
```
**Retour** : `{ profile, applied: true }`

### `node_list` — `scope: read`
Liste les nodes enrôlés (hôtes mTLS).
```json
{
  "name": "node_list",
  "description": "Liste les nodes enrôlés et leur disponibilité.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {}
  }
}
```
**Retour** : `[{ node_id, name, host, status, capacity }]`

---

## Section B — À arbitrer (spec provisoire)

### Arbitrage transverse : pattern long-running

`workspace_create`, `workspace_delete` et `workspace_apply_recipe` durent de plusieurs secondes à plusieurs minutes. Un tool MCP est requête/réponse sans streaming : un appel bloquant heurte les timeouts et ne donne aucune progression.

**Proposition (voie propre et pérenne)** : ces tools ne *réalisent* pas l'action, ils la *lancent* et retournent un `operation_id`. Une famille `operations_*` porte le suivi :

```json
{
  "name": "operations_get",
  "description": "Retourne l'état, la progression et le résultat d'une opération asynchrone.",
  "inputSchema": {
    "type": "object", "additionalProperties": false,
    "required": ["operation_id"],
    "properties": { "operation_id": { "type": "string" } }
  }
}
```
```json
{
  "name": "operations_list",
  "description": "Liste les opérations en cours, filtrables par workspace.",
  "inputSchema": {
    "type": "object", "additionalProperties": false,
    "properties": { "workspace": { "type": "string" } }
  }
}
```
**Retour `operations_get`** : `{ operation_id, kind, workspace, state: "pending"|"running"|"done"|"failed", progress, result?, error? }`

Une opération = un fichier d'état dans le stockage YAML du portail (cohérent avec l'existant).

> **Décision requise** : adopter `operations_*` pour les longs ? Si oui, cela **rétro-impacte** `workspace_start` / `stop` / `restart` du contrat principal (actuellement synchrones) — à harmoniser. Sinon, on assume le synchrone bloquant et on borne par `timeout_s`.

Les trois primitives ci-dessous sont écrites en **variante asynchrone** (sous réserve de la décision).

#### `workspace_create` — `scope: admin` — *long-running*
```json
{
  "name": "workspace_create",
  "description": "Crée un workspace depuis un repo et une recette. Asynchrone : retourne un operation_id.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["name", "repo"],
    "properties": {
      "name": { "type": "string" },
      "repo": { "type": "string", "description": "URL du dépôt git." },
      "branch": { "type": "string", "default": "dev" },
      "recipe": { "type": "string", "description": "Recette (Dev Container Features). Défaut : auto-détection." },
      "node": { "type": "string", "description": "Node cible. Défaut : placement automatique." }
    }
  }
}
```
**Retour** : `{ operation_id }` (async) — ou `{ workspace, status }` (si synchrone retenu).
> Le placement au node se fait **ici** (param `node`). La re-placement à chaud d'un workspace existant entre nodes est un sujet distinct (cf. Section C).

#### `workspace_delete` — `scope: admin` — *destructif*
```json
{
  "name": "workspace_delete",
  "description": "Supprime un workspace et son conteneur. Destructif.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["workspace", "confirm"],
    "properties": {
      "workspace": { "type": "string" },
      "confirm": { "type": "boolean", "description": "Garde anti-suppression accidentelle : doit valoir true." }
    }
  }
}
```
**Retour** : `{ operation_id }` ou `{ workspace, deleted: true }`.
> **Décision requise** : confirmation par flag `confirm` (proposé ici) suffisante, ou exiger un second appel de validation ? Vu que l'appelant peut être un agent, le flag explicite me semble le bon garde-fou minimal.

#### `workspace_apply_recipe` — `scope: admin` — *long-running*
```json
{
  "name": "workspace_apply_recipe",
  "description": "Applique/met à jour une recette (Dev Container Features) sur un workspace existant. Asynchrone.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["workspace", "recipe"],
    "properties": {
      "workspace": { "type": "string" },
      "recipe": { "type": "string" }
    }
  }
}
```
**Retour** : `{ operation_id }`.

### `agent_dispatch` — *à clarifier vs `session_send`*

Dans le tour initial, `agent_dispatch` était le lanceur de tâche asynchrone à suivi d'opération. Or `session_send` injecte déjà un prompt dans l'agent. Le recouvrement est réel et demande un choix :

- **(a) `dispatch` redondant** → on garde `session_send` (+ `capture`) comme unique mécanisme, on abandonne `dispatch`.
- **(b) `dispatch` = sur-couche à suivi** → `dispatch` = `send` + création d'une opération suivie via `operations_*`, pour les tâches longues qu'on veut traquer jusqu'à complétion sans poller le pane.

L'intérêt de (b) n'existe que si `operations_*` est adopté. **Décision couplée à l'arbitrage long-running ci-dessus.** Pas de schéma figé tant que ce n'est pas tranché.

### `workspace_secrets_*` — *flag zéro-knowledge*

Point de sécurité à ne pas manquer : l'appelant du MCP est un client conversationnel. Une primitive qui **résout et retourne** des valeurs de secret leakerait celles-ci dans le contexte de conversation et casserait le principe zéro-knowledge de Harpocrate.

**Conception propre proposée : référence et injection, jamais restitution de valeur.**

```json
{
  "name": "workspace_secrets_list",
  "description": "Liste les références de secrets (${vault://...}) liées au workspace. Noms uniquement, jamais de valeurs.",
  "inputSchema": {
    "type": "object", "additionalProperties": false,
    "required": ["workspace"],
    "properties": { "workspace": { "type": "string" } }
  }
}
```
```json
{
  "name": "workspace_secrets_bind",
  "description": "Lie une référence ${vault://...} à une cible (env var / clé de config) du workspace. La résolution reste interne au runtime ; aucune valeur n'est retournée.",
  "inputSchema": {
    "type": "object", "additionalProperties": false,
    "required": ["workspace", "reference", "target"],
    "properties": {
      "workspace": { "type": "string" },
      "reference": { "type": "string", "description": "Référence vault, ex. '${vault://bloc/nom}'." },
      "target": { "type": "string", "description": "Variable d'environnement ou clé de config cible." }
    }
  }
}
```
**Retour `bind`** : `{ target, bound: true }` — **jamais la valeur résolue.**
> La résolution effective via `SecretResolver` se produit dans la frontière workspace/portail, où l'agent la consomme. Le client ne voit que des noms.

---

## Section C — Hors périmètre / autre track

| Sujet | Raison | Destination |
|-------|--------|-------------|
| `agent_hitl_respond` | Approbation/rejet HITL : relève de l'orchestration ag.flow (console HITL), pas du pilotage workspace bas niveau. | Track HITL ag.flow. |
| `workspace_place` (re-placement à chaud) | Migrer un conteneur vivant entre hôtes = feature lourde, sans rapport avec une simple primitive. Le placement *à la création* est couvert par `workspace_create.node`. | Backlog. |
| `doc__*` / `rag__*` | Familles métier distinctes (`agflow-doc` = docflow ; `agflow-rag`). | Specs dédiées. |

---

## Récapitulatif des décisions ouvertes

1. **Pattern long-running** : adopter `operations_*` (async) ou rester synchrone ? Impacte `create` / `delete` / `apply_recipe` **et** rétro-impacte `start` / `stop` / `restart` du contrat principal.
2. **`agent_dispatch`** : (a) abandon au profit de `session_send`, ou (b) sur-couche à suivi (couplé au point 1).
3. **`workspace_delete`** : flag `confirm` suffisant, ou double validation ?
4. **`workspace_secrets_*`** : valider la conception référence/injection sans restitution de valeur.

> **Exigence (rappel du contrat principal)** : toute primitive ci-dessus, une fois figée, doit être exposée dans la documentation du produit, source de référence unique.
