# 003 — Absence de verrou de lifecycle : `up`/`stop`/`delete` concurrents corrompent l'état

- **Sévérité** : critique (viole une exigence explicite de `CLAUDE.md` : « Verrou par `ws_id` pour toute opération de lifecycle »)
- **Sous-système** : devpod
- **Fichiers** : `backend/src/portal/devpod/service.py` — `up` (~137-296), `stop` (~418-427), `delete` (~429-463), `_run_up_task` (~804-976) ; seul verrou existant : `runner.py:51` (`async with _get_lock(ws_id)`), qui n'entoure **que** le subprocess devpod.
- **Statut** : corrigé — verrou `asyncio.Lock` par `ws_id` (`service._lifecycle_locks`) détenu pour toute la durée de `up`/`stop`/`delete`/`_run_up_task` ; `delete`/`stop` **annulent** l'`up` en cours (kill subprocess + `task.cancel()`) avant d'acquérir le verrou ; écriture de statut finale gardée (`_write_status_if_exists` → `update_status_if_exists_db`, UPDATE-only atomique) qui ne ressuscite jamais une ligne supprimée.

## Symptôme

Deux opérations lifecycle concurrentes sur le même `ws_id` (deux onglets, ou UI + MCP) laissent un
état incohérent : workspace supprimé qui ressuscite, ligne DB `running` sans conteneur, tunnel SSH
et route Caddy orphelins.

## Scénario de déclenchement

Le seul verrou (`_locks[ws_id]` dans `runner.py`) protège l'exécution du **subprocess** devpod, pas
l'orchestration autour (allocation de port, port-forward, expose, écriture de statut). `up()`
retourne immédiatement et lance `_run_up_task` en tâche de fond ; `stop()` et `delete()` sont des
endpoints séparés sans verrou partagé.

- **delete pendant provisioning** : `kill_if_running` est un no-op tant que le subprocess `devpod up`
  n'est pas encore lancé (phase ssh-agent/upload). `delete` prend le verrou subprocess en premier,
  fait `devpod delete --force` + `delete_status_db`, puis `_run_up_task` prend le verrou et lance
  `devpod up` → **le workspace est créé après l'ordre de suppression**, statut réécrit `running`,
  tunnel + route Caddy créés. Workspace zombie.
- **up gagne le verrou** : `devpod up` crée le WS, puis `delete` supprime conteneur + ligne DB. Mais
  `_run_up_task` continue **hors verrou** (start_port_forward + expose + `_write_status("running")`)
  après `delete_status_db` → ligne DB `running` ressuscitée, tunnel orphelin, route Caddy fantôme.

## Cause racine

Le verrou est posé au niveau du subprocess (`runner.run_subprocess`), pas au niveau de l'opération
lifecycle complète. Toute la logique d'allocation de port, port-forward, expose et écriture de
statut vit hors de toute exclusion mutuelle inter-opérations.

## Piste de correction

Introduire un `asyncio.Lock` par `ws_id` détenu pour **toute la durée** de `up`/`stop`/`delete` et de
`_run_up_task` (pas seulement le subprocess). Comme `up` est fire-and-forget, le verrou doit être
acquis *dans* `_run_up_task`, et par `stop`/`delete`. Politique à trancher : `delete` annule ou
attend l'`up` en cours ; un marqueur « épitaphe » (ou une garde « la ligne existe-t-elle encore ? »
avant tout `_write_status` final) empêche la réécriture de statut post-delete.

## Correctif appliqué

- **Verrou lifecycle** : nouveau registre module-level `service._lifecycle_locks` (miroir de
  `runner._locks`), `_get_lifecycle_lock(ws_id)`. Détenu sur TOUT le corps de `up` (via
  `_run_up_task` qui wrappe `_run_up_impl` dans `async with _get_lifecycle_lock`), `stop` et
  `delete`. Ordre d'acquisition global unique **lifecycle → subprocess** (jamais l'inverse) :
  aucun cycle, aucun deadlock. Le verrou subprocess de `runner.py` est **conservé** (défense pour
  les appelants directs du runner ; il est toujours pris en aval du verrou lifecycle).
- **Politique delete-vs-up : ANNULATION (pas attente).** `delete` et `stop` appellent
  `_cancel_up_task(ws_id)` AVANT d'acquérir le verrou : `kill_if_running` (tue le subprocess devpod)
  + `task.cancel()` + `await task` (garantit que les `finally` ont tourné et que le verrou est
  relâché). Justification : attendre une provision de ≤30 min qu'on va détruire est absurde et
  bloquerait la requête HTTP ; annuler puis nettoyer est plus sûr et idiomatique. `CancelledError`
  est une `BaseException` : le `except Exception` de `_run_up_impl` ne l'intercepte pas, l'annulation
  se propage proprement jusqu'aux `finally` (nettoyage temp/agent) puis au verrou.
- **Épitaphe anti-résurrection** : les écritures de statut FINALES de `_run_up_impl` passent par
  `_write_status_if_exists` → `update_status_if_exists_db` (UPDATE ... WHERE ws_id, jamais d'INSERT).
  Si un `delete` concurrent a supprimé la ligne, l'UPDATE ne touche rien (rowcount 0) — pas de
  résurrection, **même si `upsert_status_db` reste un upsert inconditionnel** (bug 004/007). La garde
  est atomique côté DB (pas de fenêtre TOCTOU d'un get-puis-write).
- **Tests** : `tests/devpod/test_lifecycle_lock.py` (couche statut mockée en mémoire, sans
  Docker/Postgres) prouve exclusion mutuelle + anti-résurrection. Fixture autouse
  `service.clear_lifecycle_locks()` ajoutée à `tests/devpod/conftest.py` (rebind de boucle
  pytest-asyncio).

## Bugs liés (même cause racine)

Voir aussi [004](004-write-status-ressuscite-ligne-supprimee.md) (upsert qui recrée une ligne
supprimée), [006](006-stop-ignore-returncode-devpod.md), et le point « delete/shelve » ci-dessous.
Corriger ce verrou proprement neutralise l'essentiel des incohérences d'état.

## Vérifié

Confirmé : `grep` montre que le seul `async with _get_lock(ws_id)` est dans `runner.py:51`
(exécution du subprocess). Aucun verrou n'entoure `up`/`stop`/`delete`/`_run_up_task`.
