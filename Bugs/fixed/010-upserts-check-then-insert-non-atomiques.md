# 010 — Upserts « check-then-insert » non atomiques (UniqueViolation sous concurrence)

- **Sévérité** : majeur
- **Sous-système** : db
- **Fichiers** : `backend/src/portal/db/workspace_status.py:19-46` (`upsert_status_db`) ; `db/global_config.py:211-219` (`_write_to_db`) ; `db/user_config.py:35-54` (`ensure_user_db`), `104-117` (`save_user_db`)
- **Statut** : ✅ corrigé

## Symptôme

Sous concurrence, une opération d'upsert échoue en `UniqueViolation` (500) au lieu d'être idempotente.

## Cause racine

Le pattern est partout « `SELECT` pour décider INSERT ou UPDATE » — non atomique. Deux transactions
concurrentes en `READ COMMITTED` voient chacune l'absence de ligne, puis les deux tentent `INSERT`
sur la même PK → la seconde lève `UniqueViolation`. Concerne `upsert_status_db` (même `ws_id`),
`ensure_user_db` (deux provisions concurrentes du même login), `global_config` (id=1).

## Piste de correction

Utiliser l'upsert natif Postgres :
`sqlalchemy.dialects.postgresql.insert(...).on_conflict_do_update(...)`. Cela rend l'opération
atomique et supprime le `SELECT` préalable.

## Correction (a3991d9 + 52c8b5b)

INSERT … ON CONFLICT natif sur les quatre sites (upsert_status_db, save_user_db, ensure_user_db, global_config singleton) + provision_user au login (complément). Tests de concurrence Postgres réels (fixture db_engine_concurrent).
