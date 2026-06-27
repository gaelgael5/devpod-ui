# Ordre d'implémentation des tables SQL

Tri topologique : les tables dont dépendent les autres sont créées en premier.
Les groupes d'un même niveau peuvent être implémentés en parallèle.

---

## Groupe 0 — Tables autonomes

Aucune FK sortante. Aucune autre table n'en dépend.
Peuvent être créées en n'importe quel ordre, indépendamment du reste.

| # | Table | Source | Remarque |
|---|-------|--------|----------|
| 1 | `global_config` | `01_global_config` | Singleton `id=1`, aucune référence entrante |
| 2 | `recipe_sources` | `10_sources` | Catalogue d'URLs, aucune FK |
| 3 | `profile_sources` | `10_sources` | Catalogue d'URLs, aucune FK |
| 4 | `node_join_tokens` | `11_node_token` | Token éphémère, `node_name` sans FK stricte |

---

## Groupe 1 — Tables racines

Aucune FK sortante. Référencées par des tables des groupes suivants.

| # | Table | Source | Référencée par |
|---|-------|--------|----------------|
| 5 | `hypervisor_types` | `01_global_config` | `hypervisors` |
| 6 | `users` | `02_user_config` | `git_credentials`, `workspaces`, `workspace_status`, `recipes`, `profiles` |

---

## Groupe 2 — Dépendent des tables racines

| # | Table | Source | Dépend de |
|---|-------|--------|-----------|
| 7  | `hypervisors`       | `01_global_config` | `hypervisor_types` |
| 8  | `git_credentials`   | `02_user_config`   | `users` |
| 9  | `recipes`           | `07_recipe_shared` | `users` (FK nullable — `login IS NULL` pour scope shared/builtin) |
| 10 | `profiles`          | `09_profile`       | `users` (FK nullable — `login IS NULL` pour scope shared) |
| 11 | `workspaces`        | `02_user_config`   | `users` |
| 12 | `workspace_status`  | `12_workspace_status` | `users` (FK DEFERRABLE sur `login`) |

---

## Groupe 3 — Dépendent du groupe 2

| # | Table | Source | Dépend de |
|---|-------|--------|-----------|
| 13 | `hosts`                   | `01_global_config`    | `hypervisors` (FK DEFERRABLE sur `proxmox_node`) |
| 14 | `recipe_options`          | `07_recipe_shared`    | `recipes(key)` |
| 15 | `recipe_secret_refs`      | `07_recipe_shared`    | `recipes(key)` |
| 16 | `recipe_dependencies`     | `07_recipe_shared`    | `recipes(key)` × 2 (source + cible) |
| 17 | `workspace_ssh_keys`      | `03_ssh_workspace`    | `workspaces(login, name)` — FK composite |
| 18 | `workspace_extra_sources` | `02_user_config`      | `workspaces(id)` |
| 19 | `workspace_logs`          | `13_workspace_log`    | `workspace_status(ws_id)` — option A |
| 20 | `workspace_log_blobs`     | `13_workspace_log`    | `workspace_status(ws_id)` — option B |
| 21 | `workspace_build_contexts`| `14_devcontainer_tmp` | `workspace_status(ws_id)` — table optionnelle |

---

## Groupe 4 — Dépendent du groupe 3

| # | Table | Source | Dépend de |
|---|-------|--------|-----------|
| 22 | `node_certificates` | `06_node_cert` | `hosts(name)` |

---

## Graphe de dépendances

```
global_config ──────────────────────────────── (autonome)
recipe_sources ─────────────────────────────── (autonome)
profile_sources ────────────────────────────── (autonome)
node_join_tokens ───────────────────────────── (autonome)

hypervisor_types ───► hypervisors ──────────► hosts ──► node_certificates
                                          ↗
users ──────────────► hypervisors (proxmox_node, DEFERRABLE)
       │
       ├──► git_credentials
       ├──► workspaces ──► workspace_extra_sources
       │              └──► workspace_ssh_keys
       ├──► recipes ──► recipe_options
       │           └──► recipe_secret_refs
       │           └──► recipe_dependencies (× 2)
       ├──► profiles
       └──► workspace_status ──► workspace_logs
                             └──► workspace_log_blobs
                             └──► workspace_build_contexts (optionnel)
```

---

## Notes d'implémentation

- **FK circulaire apparente** : `hosts.proxmox_node → hypervisors(name)` est déclarée `DEFERRABLE INITIALLY DEFERRED`. Créer d'abord `hypervisors`, puis `hosts`. Insérer dans `hosts` avec `proxmox_node = ''` (DEFAULT) si l'hyperviseur n'existe pas encore, mettre à jour ensuite.
- **PK composite avec NULL** : `recipes` et `profiles` utilisent `PRIMARY KEY (id/slug, scope, COALESCE(login, ''))`. PostgreSQL ne supporte pas `COALESCE` dans une PK déclarative — implémenter via un index unique partiel ou une colonne `login_key TEXT GENERATED ALWAYS AS (COALESCE(login, '')) STORED`.
- **Tables optionnelles** : `workspace_build_contexts` (groupe 3, #21) n'est requise que si l'observabilité des builds est souhaitée. Elle peut être créée après les autres tables du groupe 3.
- **Option A vs B** : `workspace_logs` (#19) et `workspace_log_blobs` (#20) sont mutuellement exclusives. Choisir l'une avant migration. La recommandation du fichier source est l'option B.
