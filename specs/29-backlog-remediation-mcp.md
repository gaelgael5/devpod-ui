# Backlog remédiation — Surface MCP devpod

Issu de l'audit du 2026-07-01. Voir `28-audit-outils-mcp.md` pour la grille complète.

Priorités :
- **P0** : cohérence IDs cassée → bloque le raisonnement inter-outils
- **P1** : état live manquant, champs critiques absents → dégradation silencieuse
- **P2** : confort agent (nommage, descriptions, timestamps)

---

## P0 — Cohérence IDs

### [R-01] workspace_messages : renommer `workspace_name` → `workspace`

**Outil(s) :** `workspace_messages`
**Problème :** Paramètre d'entrée nommé `workspace_name` au lieu de `workspace`. Seule exception dans toute la surface : les 22 autres outils de la famille workspace_* et les 7 session_* utilisent `workspace`.
**Impact agent :** Toute pattern générique de paramétrage (boucle, métaprompt) échoue sur cet outil. L'agent doit mémoriser une exception ad hoc.
**Fix proposé :** Renommer dans registry.py (`"required": ["workspace"]`, clé `workspace`) et dans message_tools.py accepter les deux noms en transition (`args.get("workspace") or args.get("workspace_name")`), supprimer `workspace_name` au sprint suivant.
**Effort :** S
**Rétrocompat :** non (renommage de paramètre) — transition double-nom obligatoire.

---

### [R-02] Nœud cible : harmoniser `node` → `node_id` dans la famille workspace_*

**Outil(s) :** `workspace_create` (param `node`), `workspace_list` (réponse `node`), `workspace_get` (réponse `node`), `workspace_status` (manquant)
**Problème :** La famille compose_* et `node_list` utilisent `node_id`. La famille workspace_* utilise `node`. Un agent qui apprend le contrat depuis `node_list` va utiliser `node_id` dans `workspace_create` et obtenir une erreur silencieuse (champ ignoré = node auto).
**Impact agent :** Placement de workspace sur un nœud spécifique impossible de façon fiable si l'agent a appris la convention depuis node_list ou compose_service_start.
**Fix proposé :**
- `workspace_create` : accepter `node_id` en alias de `node` (transition)
- `_ws_summary` / `_workspace_get` : retourner `"node_id": spec.host or None` en plus de `"node"` (deprecated)
- `workspace_status` : ajouter `node_id` dans la réponse

**Effort :** M
**Rétrocompat :** non pour le paramètre d'entrée. Réponse : oui (ajout de champ).

---

### [R-03] Clé `recipe` → `recipes` dans les réponses workspace_list et workspace_get

**Outil(s) :** `workspace_list`, `workspace_get`
**Problème :** Les deux outils retournent `"recipe": [...]` (singulier) pour un array. `workspace_create` prend `"recipes"` (pluriel). `workspace_apply_recipe` prend `"recipe"` (singulier = une recette à appliquer). Ambiguïté maximale.
**Impact agent :** Un agent qui lit `recipe` depuis workspace_get et le passe à workspace_create sous le même nom obtient une erreur (champ inconnu) ou l'ignore.
**Fix proposé :** Dans `_ws_summary` et `_workspace_get`, émettre `"recipes": spec.recipes` (nouveau) + `"recipe": spec.recipes` (deprecated) pendant une transition, puis supprimer `recipe`.
**Effort :** S
**Rétrocompat :** non (renommage de clé) — double-émission obligatoire.

---

### [R-04] workspace_status : erreur explicite si workspace inconnu

**Outil(s) :** `workspace_status`
**Problème :** `_require_ws` valide seulement le format regex du nom, pas son existence dans la config. Si le workspace n'existe pas, `get_service().status()` retourne `{"status": "unknown"}` sans erreur. L'agent interprète "unknown" comme un état transitoire valide.
**Impact agent :** Boucle de poll infinie sur un workspace inexistant. Diagnostic impossible depuis la réponse seule.
**Fix proposé :** Dans `_workspace_status`, ajouter une vérification d'existence après `_require_ws` (charger `load_user_db` et chercher le spec, comme dans `_workspace_get`). Si absent → `raise DevpodToolError(f"workspace inconnu: {name}")`.
**Effort :** S
**Rétrocompat :** oui (durcissement d'erreur, les appels valides ne changent pas).

---

## P1 — État live manquant / Champs critiques absents

### [R-05] workspace_get : ajouter profile, init_recipes, env

**Outil(s) :** `workspace_get`
**Problème :** Les champs `profile`, `init_recipes` et `env` (bindings secrets) sont dans WorkspaceSpec mais absents de la réponse workspace_get. Un agent ne peut pas reconstruire le spec complet sans ces champs.
**Impact agent :** Impossible de vérifier le profil VS Code actif avant workspace_profile_set. Impossible de lister les recettes d'init disponibles. Impossible de voir les bindings secrets actifs (déjà dans workspace_secrets_list, mais la référence croisée n'est pas faite).
**Fix proposé :** Dans `_workspace_get`, compléter le retour avec :
- `"profile": f"{spec.profile.scope}/{spec.profile.slug}" if spec.profile else None`
- `"init_recipes": spec.init_recipes or []`
- `"secret_bindings": {k: v for k, v in (spec.env or {}).items() if _SECRET_REF_RE.fullmatch(v or "")}` (noms uniquement, ref vault safe à exposer)

**Effort :** S
**Rétrocompat :** oui (ajout de champs).

---

### [R-06] operations_get / operations_list : exposer created_at et updated_at

**Outil(s) :** `operations_get`, `operations_list`
**Problème :** Le YAML de chaque opération contient `created_at` et `updated_at` mais ils sont filtrés hors de la réponse retournée.
**Impact agent :** Un agent qui poll `operations_get` ne peut pas mesurer le temps écoulé depuis le lancement ni détecter un blocage. Un agent qui liste des opérations ne peut pas les trier par ancienneté.
**Fix proposé :** Dans `_operations_get`, ajouter `"created_at"` et `"updated_at"` dans le tuple de clés extraites du dict op (ils sont déjà présents dans le YAML). Dans `_operations_list`, ajouter `"created_at"` idem.
**Effort :** S
**Rétrocompat :** oui (ajout de champs).

---

### [R-07] compose_service_list : documenter le status déclaratif et ajouter created_at

**Outil(s) :** `compose_service_list`
**Problème :** Le status dans la liste vient de la DB (pas de refresh). `compose_service_status` fait le refresh live. Cette différence n'est pas documentée. De plus, `created_at` est absent des items de liste.
**Impact agent :** Un agent qui liste les déploiements et prend des décisions sur leur status travaille sur des données potentiellement stales sans le savoir. Pas de datum temporel pour distinguer les déploiements récents.
**Fix proposé :** Dans `_compose_service_list`, ajouter `"created_at": d.created_at.isoformat() if d.created_at else None`. Compléter la description MCP : `"status: déclaratif (DB) — appeler compose_service_status pour rafraîchir."`.
**Effort :** S
**Rétrocompat :** oui (ajout de champs).

---

### [R-08] workspace_list : ajouter branch et created_at

**Outil(s) :** `workspace_list`
**Problème :** `branch` et `created_at` sont dans WorkspaceSpec/workspace_status mais absents de la liste. Un agent qui cherche les workspaces sur une branche doit appeler workspace_get pour chacun.
**Impact agent :** N appels workspace_get pour une simple question "quels workspaces sont sur la branche dev ?".
**Fix proposé :** Dans `_ws_summary`, ajouter `"branch": spec.branch or None` (trivial). Pour `created_at` : le WorkspaceSpec issu de `load_user_db` n'expose pas la date DB. Deux options : (a) requête `ws_table` supplémentaire pour joindre `created_at` ; (b) opt-in `include=["dates"]` pour ne pas systématiser le coût. Option (b) préférée pour rester dans le modèle `node_list`.
**Effort :** M (branch=S, created_at=M si opt-in)
**Rétrocompat :** oui (ajout de champs).

---

## P2 — Confort agent

### [R-09] workspace_profile_set : corriger le scope de "write" à "exec"

**Outil(s) :** `workspace_profile_set`
**Problème :** Scope = "write" dans le registre, mais l'impact est "destructive-sessions" (delete + recréation complète du conteneur). `workspace_restart` a le même impact et scope "admin". L'inconsistance peut induire un enforcement RBAC incorrect.
**Fix proposé :**
```python
"scope": "admin",  # était "write"
```
**Effort :** S (une ligne)
**Rétrocompat :** non (restriction de scope). Impact limité aux apikeys avec scope write qui utilisent cet outil.

---

### [R-10] workspace_exec : documenter stderr=stdout dans la description MCP

**Outil(s) :** `workspace_exec`
**Problème :** `stderr` est toujours `""` dans la réponse car stdout+stderr sont fusionnés par `ws_exec`. C'est documenté dans un commentaire Python mais pas dans la description MCP visible par l'agent.
**Impact agent :** Un agent qui cherche des erreurs dans le champ `stderr` les trouvera vides même quand la commande a écrit sur stderr. Les erreurs apparaissent dans `stdout`.
**Fix proposé :**
```python
# registry.py, description de workspace_exec
"Impact: write-safe — exécute dans le conteneur en cours ; "
"pas de redémarrage du conteneur. "
"Note: stdout et stderr sont fusionnés dans le champ 'stdout' (v1) ; "
"'stderr' est toujours vide."
```
**Effort :** S (description uniquement)
**Rétrocompat :** oui.

---

### [R-11] workspace_logs : marquer `since` comme inefficace dans le schéma

**Outil(s) :** `workspace_logs`
**Problème :** `since` est dans le schéma avec description "Réservé v1 (non appliqué)". Un agent peut l'utiliser croyant filtrer par timestamp, sans avertissement visible dans le schéma lui-même.
**Fix proposé :**
```python
"since": {
    "type": "string",
    "description": "NON IMPLÉMENTÉ en v1 — ignoré. Filtrage à venir.",
},
```
**Effort :** S
**Rétrocompat :** oui.

---

### [R-12] gateway__list_backends : enrichir description et réponse

**Outil(s) :** `gateway__list_backends`
**Problème :**
- Description trop courte : pas d'Impact line, pas de guide vs node_list
- Réponse manque `url`, `id` (pour croiser les logs audit), `app_url`, `transport`
- `health` vient du monitoring périodique (pas live), non documenté
- `inputSchema` sans `additionalProperties: false`

**Impact agent :** L'agent ne sait pas que health peut être "unknown" si le backend n'a jamais été sondé. Il ne peut pas construire l'URL de l'application sans un appel HTTP supplémentaire.
**Fix proposé :** Dans `_gateway_list_backends` (handlers.py), ajouter `"url"`, `"transport"`, `"app_url"` dans le payload. Compléter la description : Impact line + `"health = état du dernier monitoring périodique ; 'unknown' si jamais sondé."`.
**Effort :** S
**Rétrocompat :** oui (ajout de champs).

---

### [R-13] session_list : ajouter uptime_s par session

**Outil(s) :** `session_list`
**Problème :** `session_list` retourne `{session_id, name, command, alive}`. `alive` est toujours True (par construction). Pas d'uptime. Un agent doit appeler `session_get` pour chaque session pour avoir l'uptime.
**Impact agent :** N appels session_get avant une décision de session_close/restart.
**Fix proposé :** Utiliser le même format `list-sessions -F '#{session_name}|#{pane_current_command}|#{session_created}'` pour inclure `session_created`, calculer uptime_s.
**Effort :** S
**Rétrocompat :** oui (ajout de champ).

---

## Ordre de remédiation suggéré

### Sprint 1 (P0, ~2-3 jours)
1. [R-01] workspace_messages : transition workspace_name → workspace
2. [R-04] workspace_status : vérification d'existence du workspace
3. [R-03] recipe → recipes dans les réponses (transition double-clé)

### Sprint 2 (P0+P1 légers, ~2-3 jours)
4. [R-05] workspace_get : ajouter profile, init_recipes, secret_bindings
5. [R-06] operations : exposer created_at, updated_at
6. [R-09] workspace_profile_set : scope write → admin
7. [R-10] workspace_exec : documenter stderr=stdout
8. [R-11] workspace_logs : marquer since comme inefficace
9. [R-12] gateway__list_backends : description + réponse enrichie

### Sprint 3 (P1 coûteux + P2, ~3-4 jours)
10. [R-02] Harmoniser node → node_id (workspace_*)
11. [R-07] compose_service_list : status déclaratif + created_at
12. [R-08] workspace_list : branch + created_at
13. [R-13] session_list : uptime_s
