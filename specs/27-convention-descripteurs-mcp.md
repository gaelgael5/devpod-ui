# Convention — Descripteurs MCP (surface devpod)

Généralisée depuis l'audit complet des 45 outils (2026-07-01).
Le cas pilote est `node_list` après son dernier fix.

---

## 1. Structure de descripteur type

```python
"tool_name": {
    "description": (
        "Phrase de rôle : quoi + quand utiliser CEL outil et pas ses voisins. "
        "\n\nChamps clés : champ1 (sémantique), champ2 (sémantique). "
        "Impact: <niveau> — détail one-liner."
    ),
    "inputSchema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["champ_obligatoire"],
        "properties": { ... },
    },
    "scope": "read|write|exec|admin",
}
```

### Champs obligatoires dans la description

| Bloc | Contenu |
|---|---|
| Phrase de rôle | Ce que l'outil fait, son périmètre exact. |
| Différenciation | 1 phrase courte si un outil voisin fait quelque chose de proche. |
| Champs clés | Nommer les champs non-évidents + leur sémantique. |
| Impact | `read-only`, `write-safe`, `non-destructive`, `destructive-sessions`, `destructive-data`. |

---

## 2. Règles d'identité — IDs joignables cross-familles

### Règle fondamentale

**Un ID retourné dans une réponse doit être utilisable tel quel comme paramètre d'entrée du tool suivant, sans transformation.**

Exemples :
- `workspace_list` → `name` → paramètre `workspace` de tous les outils workspace_*
- `node_list` → `node_id` → paramètre `node_id` de `compose_service_start` et filtre `compose_service_list`
- `compose_service_list` → `id` (slug) → paramètre `deployment_id` de stop/restart/logs/status/down

### Nommage canonique des identifiants

| Concept | Nom de paramètre d'entrée | Nom dans la réponse |
|---|---|---|
| Workspace | `workspace` | `name` (+ `id` = "login-name" pour référence interne uniquement) |
| Node / host Docker | `node_id` | `node_id` |
| Déploiement compose | `deployment_id` | `id` (slug) |
| Template compose | `template_id` | `id` |
| Opération async | `operation_id` | `operation_id` |
| Session tmux | `session` | `name` (+ `session_id` = "workspace:session") |

### Règle de pluriel

- Array de valeurs → clé au **pluriel** : `recipes`, `tags`, `host_ports`, `references`
- Scalaire ou paramètre d'entrée → **singulier** : `recipe` (une recette à appliquer), `workspace`

---

## 3. État live vs déclaratif

### Quand exiger un timestamp ?

| Cas | Règle |
|---|---|
| Status venant d'une probe live à l'appel | Pas de timestamp obligatoire, mais documenter "mesuré à l'appel" dans la description. |
| Status venant de la DB sans refresh | Documenter "déclaratif (DB)" et pointer l'outil de refresh live. |
| Opération asynchrone | `created_at` + `updated_at` obligatoires dans la réponse. |
| Objet listable (workspace, déploiement…) | `created_at` dans chaque item de liste. |

### Honnêteté sur les limites

Si une métrique n'est pas encore collectée, retourner `null` **avec documentation explicite** du pourquoi et du plan (ex. node_list : `"reachable": null` avec mention "probe live non implémenté"). Ne jamais inventer une valeur.

---

## 4. Principe summary + drill-down

### Règle

Les outils de **liste** retournent des compteurs + pointeurs. Les détails vivent dans l'outil `get` correspondant.

| Ce qui appartient à la liste | Ce qui appartient au get |
|---|---|
| id, name, status, node, created_at | Tous les champs de config (branch, recipes, profile, env, sessions, ...) |
| Compteurs (nb sessions, nb recipes) | Contenu détaillé (YAML, diff, output) |

### Enrichissement opt-in : `include`

Pour les outils qui peuvent retourner des données coûteuses, paramètre `include: ["champ"]`.

```json
{ "include": ["workload"] }
```

Les champs non demandés ne sont pas calculés. Les champs "Vague future" retournent `null` avec documentation.

---

## 5. Gestion d'erreur

### Ce que l'outil doit retourner quand la cible n'existe pas

```python
raise DevpodToolError(f"workspace inconnu: {name}")
```

**Ne jamais** retourner un status `"unknown"` ou une réponse vide quand la cause réelle est une cible inexistante. L'agent ne peut pas distinguer "workspace existe mais état inconnu" de "workspace n'existe pas" si les deux retournent `{"health": "unknown"}`.

### Matrice de comportements attendus

| Situation | Comportement |
|---|---|
| Paramètre format invalide | `DevpodToolError` immédiat, message précis |
| Cible inexistante (workspace, déploiement) | `DevpodToolError("X inconnu: Y")` |
| Opération partiellement échouée | `isError=True`, message exploitable (pas de stacktrace) |
| Fonctionnalité non implémentée | Valeur `null` documentée, jamais une erreur 500 |

---

## 6. Nommage cohérent — conventions à respecter

### Paramètres d'entrée

- Toujours `workspace` pour référencer un workspace (jamais `workspace_name`, `ws_id`, `ws_name`)
- Toujours `node_id` pour référencer un nœud (jamais `node`, `host`, `host_id`)
- Toujours `deployment_id` pour un déploiement compose
- Toujours `session` pour le nom de session tmux (défaut `"main"`)

### Champs de sortie cohérents

- Status d'un objet → `status` (jamais `health` pour les workspaces, `state` pour les ops)
- Date de création → `created_at` (ISO 8601 avec timezone)
- Date de mise à jour → `updated_at`
- Tableau de recettes → `recipes` (jamais `recipe` pour un tableau)
- Nœud cible → `node_id` (jamais `node` dans les réponses)

### Scope vs Impact

| Scope | Impact maximal |
|---|---|
| `read` | `read-only` |
| `write` | `write-safe` |
| `exec` | `non-destructive` ou `destructive-sessions` |
| `admin` | Tout niveau, y compris `destructive-data` |

Un outil `destructive-sessions` doit avoir scope `exec` ou `admin`, jamais `write`.

---

## 7. Rétrocompatibilité

### Ajouter des champs → sûr

Ajouter un champ dans une réponse est toujours rétrocompatible : les clients qui ne le connaissent pas l'ignorent.

```python
# Sûr : ajout d'un champ optionnel
return {**existing_response, "created_at": ...}
```

### Changer la sémantique d'un champ → breaking

Changer le nom, le type ou la sémantique d'un champ existant nécessite :
1. Ajouter le nouveau champ en parallèle de l'ancien
2. Documenter l'ancien comme déprécié avec une version cible de suppression
3. Attendre qu'aucun agent actif ne lise l'ancien

### Changer un paramètre d'entrée obligatoire → breaking

Renommer un paramètre d'entrée (ex. `workspace_name` → `workspace`) nécessite :
1. Accepter les deux noms en lecture pendant une période de transition
2. Documenter la migration dans le schéma : `"deprecated": "workspace_name is deprecated, use workspace"`
