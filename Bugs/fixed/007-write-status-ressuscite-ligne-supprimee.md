# 007 — `_write_status` (upsert) ressuscite une ligne de workspace supprimée

- **Sévérité** : majeur
- **Sous-système** : devpod / db
- **Fichiers** : `backend/src/portal/devpod/service.py` — `_run_up_task` fin (`_write_status(ws_id, status, ...)` ~948, branche `except` → `"failed"` ~954) ; `_write_status` fait un `upsert` (INSERT-or-UPDATE) inconditionnel via `upsert_status_db`
- **Statut** : ✅ corrigé

## Symptôme

Un workspace supprimé réapparaît dans les listings avec le statut `failed` ou `running`.

## Scénario de déclenchement

Un `delete` concurrent (ou un `kill_if_running` qui interrompt le `devpod up`) fait tomber le
subprocess ; `run_subprocess` retourne un rc négatif → `_run_up_task` écrit `failed` via
`upsert_status_db` **après** que `delete` a fait `delete_status_db`. Comme l'écriture est un upsert,
la ligne est **recréée**.

## Cause racine

`_write_status` fait un `upsert` inconditionnel : il recrée la ligne si elle a été supprimée entre
la lecture initiale et l'écriture finale. Sous-cas concret de
[003](003-absence-verrou-lifecycle-workspace.md), mais corrigeable indépendamment.

## Piste de correction

Après le subprocess, ne réécrire le statut que si la ligne existe encore (UPDATE-only, ou garde
`if get_status_db(ws_id) is not None`). Idéalement combiné au verrou lifecycle de 003.

## Correction (dfdbb22)

Les écritures finales de _run_up_task étaient déjà gardées par l'épitaphe du bug 003 ; stop() bascule aussi sur _write_status_if_exists — règle uniforme : seul up() crée la ligne, toute autre écriture de statut est UPDATE-only.
