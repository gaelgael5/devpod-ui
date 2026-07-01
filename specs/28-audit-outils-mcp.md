# Audit — Surface MCP devpod (45 outils)

Grille d'évaluation : 9 critères.
Légende : ✓ OK · ⚠ partiel · ✗ problème

Colonnes abrégées :
**Compl** = Complétude · **IDs** = Cohérence IDs · **Live** = État live vs déclaratif
**S+D** = Summary+drill-down · **FP** = Frontière produit · **CdV** = Cycle de vie
**Desc** = Clarté description · **Err** = Comportement d'échec · **Trans** = Cohérence transverse

---

## Famille workspace_* (22 outils)

| Outil | Compl | IDs | Live | S+D | FP | CdV | Desc | Err | Trans | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| `workspace_list` | ⚠ | ✓ | ⚠ | ✓ | ✓ | ✗ | ✓ | ✓ | ⚠ | Manque branch, created_at. Status sans timestamp. Clé `recipe` (sing.) vs `recipes` dans create. `id` retourné = "login-name" non actionnable. |
| `workspace_get` | ⚠ | ✓ | ✓ | ✓ | ✓ | ⚠ | ✓ | ✓ | ⚠ | Manque profile, init_recipes, env (bindings secrets). created_at ✓, pas updated_at. Clé `recipe` sing. |
| `workspace_status` | ⚠ | ✓ | ✓ | ⚠ | ✓ | ✗ | ✓ | ✗ | ⚠ | Probe live ✓ mais pas de timestamp. Manque node, url VS Code. Workspace inexistant → retourne "unknown" sans erreur. Clé `health` au lieu de `status`. |
| `workspace_create` | ✓ | ✓ | — | — | ✓ | ✓ | ✓ | ✓ | ✓ | based_on ✓. Asynchrone ✓. repo→source remapping documenté. |
| `workspace_delete` | ✓ | ✓ | — | — | ✓ | ✓ | ✓ | ✓ | ✓ | confirm guard ✓. Asynchrone ✓. |
| `workspace_logs` | ⚠ | ✓ | ✓ | ✓ | ✓ | ✗ | ⚠ | ⚠ | ✓ | `since` décrit "réservé v1 non appliqué" dans description mais présent dans le schéma sans mise en garde → agent peut l'utiliser croyant filtrer. File absent → output="" silencieux. |
| `workspace_resources` | ⚠ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | Pas d'unités dans la description (bytes/pourcent). mem_limit "max" → None non documenté. |
| `workspace_git_status` | ⚠ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | Manque ahead/behind remote. |
| `workspace_git_commit` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | Garde branche "dev" ✓. |
| `workspace_exec` | ⚠ | ✓ | ✓ | ✓ | ✓ | ✗ | ⚠ | ✓ | ✓ | stderr toujours "" (stdout+stderr fusionnés) non documenté dans la description MCP. exit_code présent ✓. |
| `workspace_tree` | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | |
| `workspace_read_file` | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | size+sha256 ✓. |
| `workspace_write_file` | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | Écriture atomique ✓. |
| `workspace_mkdir` | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | |
| `workspace_secrets_list` | ✓ | ✓ | — | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | |
| `workspace_secrets_bind` | ✓ | ✓ | — | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | |
| `workspace_reconnect` | ✓ | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | Distinction vs restart bien documentée. |
| `workspace_stop` | ✓ | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| `workspace_restart` | ✓ | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| `workspace_apply_recipe` | ✓ | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | Asynchrone ✓. |
| `workspace_profile_set` | ✓ | ✓ | — | ✓ | ✓ | ✓ | ⚠ | ✓ | ✗ | scope="write" mais impact "destructive-sessions" → devrait être scope="admin" (ou "exec") comme workspace_restart. |
| `workspace_messages` | ✓ | ✗ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | **CRITIQUE** : paramètre `workspace_name` au lieu de `workspace` — seule exception dans la surface entière (22 outils utilisent `workspace`). |

---

## Famille session_* (7 outils)

| Outil | Compl | IDs | Live | S+D | FP | CdV | Desc | Err | Trans | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| `session_open` | ✓ | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | Idempotent ✓. session_id="ws:session" ✓. |
| `session_list` | ⚠ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | alive=True toujours (par construction). Manque uptime, created_at. |
| `session_get` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | uptime_s ✓. pane_id ✓. |
| `session_send` | ✓ | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | _origin/_depth réservés documentés ✓. |
| `session_capture` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ANSI inclus (-e) documenté dans commentaire, pas dans la description MCP. |
| `session_interrupt` | ✓ | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| `session_close` | ✓ | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |

---

## Famille compose_service_* (7 outils)

| Outil | Compl | IDs | Live | S+D | FP | CdV | Desc | Err | Trans | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| `compose_service_list` | ⚠ | ✓ | ✗ | ✓ | ✓ | ✗ | ⚠ | ✓ | ✓ | Status déclaratif (DB, pas refresh). Manque created_at, template_name. Description ne mentionne pas le caractère déclaratif du status. |
| `compose_service_status` | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | refresh_status live ✓. Manque last_refreshed timestamp. |
| `compose_service_start` | ⚠ | ✓ | — | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | Manque created_at dans la réponse. Asynchronisme non annoncé (synchrone). |
| `compose_service_stop` | ✓ | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | Synchrone (pas d'op_id), cohérent avec restart. |
| `compose_service_restart` | ✓ | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| `compose_service_logs` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| `compose_service_down` | ✓ | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | confirm guard ✓. |

---

## Famille compose_template_* (4 outils)

| Outil | Compl | IDs | Live | S+D | FP | CdV | Desc | Err | Trans | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| `compose_template_list` | ✓ | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | `parameters` = count (int) dans la liste, array dans get. Bon drill-down. |
| `compose_template_get` | ✓ | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | model_dump complet ✓. |
| `compose_template_create` | ✓ | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | warnings retournés ✓. |
| `compose_template_update` | ✓ | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | Partial update (compose_content requis, autres optionnels) ✓. |

---

## Famille operations_* (2 outils)

| Outil | Compl | IDs | Live | S+D | FP | CdV | Desc | Err | Trans | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| `operations_get` | ⚠ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | created_at, updated_at présents dans le YAML sous-jacent mais **absents** de la réponse retournée. |
| `operations_list` | ⚠ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | Même problème : pas de created_at dans la réponse. |

---

## Outils singuliers

| Outil | Compl | IDs | Live | S+D | FP | CdV | Desc | Err | Trans | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| `node_list` (**référence**) | ✓ | ✓ | ⚠ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | reachable=null honnêtement documenté. workload opt-in ✓. Référence pour les autres familles. |
| `portal_reload` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | reason field ✓. |
| `gateway__list_backends` | ✗ | ✓ | ⚠ | ✗ | ✓ | ✗ | ✗ | ✓ | ⚠ | Manque url, id, app_url, transport dans la réponse. health = valeur en mémoire (mise à jour par monitoring périodique, pas live). Description très courte, pas d'Impact line. inputSchema sans additionalProperties:false. |

---

## Synthèse des patterns récurrents

### Pattern 1 : Nommage divergent du même concept

Le concept "nœud cible" a deux noms selon la famille :
- Famille workspace_* : paramètre `node`, clé de réponse `node` 
- Famille compose_* : paramètre `node_id`, clé de réponse `node_id`
- `node_list` retourne `node_id`

Un agent qui apprend "le nœud s'appelle node_id depuis node_list" et essaie workspace_create avec `node_id` va échouer (le champ s'appelle `node` dans workspace_create).

### Pattern 2 : Singulier/pluriel inconsistant pour les recettes

- `workspace_list` et `workspace_get` retournent `recipe` (singulier) pour un array
- `workspace_create` prend `recipes` (pluriel)
- `workspace_apply_recipe` prend `recipe` (singulier, un seul élément)

### Pattern 3 : workspace_messages rompt le contrat universel

23 outils sur 23 familles workspace/session utilisent `workspace` comme paramètre. `workspace_messages` seul utilise `workspace_name`. Toute pattern de paramétrage générique échoue sur cet outil.

### Pattern 4 : Status déclaratif non signalé

`compose_service_list` retourne le status en base (pas live) tandis que `compose_service_status` fait un refresh. La description de `compose_service_list` ne le signale pas. Un agent qui prend des décisions sur le status de la liste sans appeler compose_service_status travaille sur des données potentiellement stales.

### Pattern 5 : Timestamps manquants dans les réponses d'opérations

`operations_get` et `operations_list` stockent `created_at`/`updated_at` dans leur YAML mais ne les retournent pas. Un agent qui poll `operations_get` ne peut pas mesurer le temps écoulé depuis le lancement.

### Pattern 6 : Erreur silencieuse pour workspace inexistant

`workspace_status` appelle `_require_ws` (validation de format uniquement) puis `get_service().status()`. Si le workspace n'existe pas dans la config, le status retourné est "unknown" sans erreur. L'agent interprète "unknown" comme un état transitoire valide et peut boucler indéfiniment.
