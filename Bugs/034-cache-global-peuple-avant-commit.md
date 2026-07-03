# 034 — Le cache global est peuplé avant le commit de la transaction

- **Sévérité** : mineur
- **Sous-système** : db / config
- **Fichiers** : `db/global_config.py:60-65` (`save_global_db` fait `_cache = cfg`) appelé depuis `config/store.py:98-103`
- **Statut** : ouvert

**Symptôme** : `save_global_db` positionne `_cache = cfg` **à l'intérieur** du bloc
`async with begin()`. Si le `COMMIT` échoue à la sortie du contexte, la DB rollback mais `_cache`
contient déjà la config **non commitée** → toutes les lectures suivantes (`get_cached_global`) servent
un état fantôme jusqu'au prochain `warm_global_cache` (redémarrage).

**Correction** : mettre à jour `_cache` seulement **après** le commit réussi (dans `store.save_global`,
après la sortie du `begin()`), pas dans la fonction DB.
