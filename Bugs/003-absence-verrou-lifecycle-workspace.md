# 003 — Absence de verrou de lifecycle : `up`/`stop`/`delete` concurrents corrompent l'état

- **Sévérité** : critique (viole une exigence explicite de `CLAUDE.md` : « Verrou par `ws_id` pour toute opération de lifecycle »)
- **Sous-système** : devpod
- **Fichiers** : `backend/src/portal/devpod/service.py` — `up` (~137-296), `stop` (~418-427), `delete` (~429-463), `_run_up_task` (~804-976) ; seul verrou existant : `runner.py:51` (`async with _get_lock(ws_id)`), qui n'entoure **que** le subprocess devpod.
- **Statut** : ouvert

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

## Bugs liés (même cause racine)

Voir aussi [004](004-write-status-ressuscite-ligne-supprimee.md) (upsert qui recrée une ligne
supprimée), [006](006-stop-ignore-returncode-devpod.md), et le point « delete/shelve » ci-dessous.
Corriger ce verrou proprement neutralise l'essentiel des incohérences d'état.

## Vérifié

Confirmé : `grep` montre que le seul `async with _get_lock(ws_id)` est dans `runner.py:51`
(exécution du subprocess). Aucun verrou n'entoure `up`/`stop`/`delete`/`_run_up_task`.
