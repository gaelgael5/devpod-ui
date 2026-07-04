# 004 — Le champ `culture` de `UserConfig` n'est ni écrit ni relu (perte silencieuse)

- **Sévérité** : majeur (perte de donnée silencieuse d'une préférence utilisateur, sans erreur)
- **Sous-système** : config / db
- **Fichiers** : `backend/src/portal/db/user_config.py` (écriture `save_user_db` ~104-124, lecture `_build_user_config` ~181-191) ; colonne `db/tables.py:178` ; champ `config/models.py:374` ; route `routes/me.py:96-104`
- **Statut** : corrigé — `culture` ajouté à `user_vals` (écriture) et `_build_user_config` (lecture) dans `db/user_config.py`, test de round-trip ajouté

## Symptôme

Un utilisateur change sa langue (`PUT /me/config {"culture":"en"}`) : la requête réussit (200), mais
la préférence n'est jamais persistée. Toute relecture, et tout message workspace généré par
`compose/service.py` (qui consomme `user_cfg.culture` pour choisir la langue), retombe sur `"fr"`.

## Cause racine

La colonne `users.culture` (`server_default="fr"`) et le champ pydantic `UserConfig.culture` existent,
mais **aucun des deux sens du mapping DB↔modèle ne les relie** :
- `save_user_db` construit `user_vals` **sans** `culture` → la colonne garde son défaut ;
- `_build_user_config` construit `UserConfig(...)` **sans** passer `user_row["culture"]` → le modèle
  retombe sur le défaut `"fr"`.

Vérifié : `grep culture` sur `db/user_config.py` ne retourne **aucune** occurrence (ni écriture ni
lecture de `users.c.culture`), alors que la colonne et le champ existent.

## Piste de correction

- Ajouter `"culture": cfg.culture` dans `user_vals` (INSERT et UPDATE de `save_user_db`).
- Ajouter `culture=user_row["culture"]` dans `_build_user_config`.
- Ajouter un test de round-trip `culture="en"` → save → load → `== "en"`.
