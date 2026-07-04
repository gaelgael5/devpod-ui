# 034 — Le cache global est peuplé avant le commit de la transaction

- **Sévérité** : mineur
- **Sous-système** : db / config
- **Fichiers** : `db/global_config.py:60-65` (`save_global_db` fait `_cache = cfg`) appelé depuis `config/store.py:98-103`
- **Statut** : corrigé — `save_global_db` (db/global_config.py) ne touche plus `_cache` (il est
  encore dans la transaction de l'appelant à ce stade, avant COMMIT). Nouvelle fonction
  `set_cached_global(cfg)` qui peuple le cache sans I/O DB, appelée par l'appelant après un COMMIT
  réussi. `config/store.py::save_global` l'appelle après la sortie du bloc `begin()`, comme prescrit.
  **Extension de portée nécessaire** : `save_global_db` a ~14 autres appelants directs
  (`routes/admin.py` ×10, `routes/test_vm.py` ×4) qui dépendaient tous du même effet de bord pour
  garder le cache synchronisé — les laisser tels quels aurait remplacé le bug (cache prématuré) par
  une régression pire (cache jamais resynchronisé après ces routes). Chacun appelle désormais
  `set_cached_global(cfg)` : juste après le bloc `begin()` dédié pour les 6 qui en ouvrent un propre
  (comportement désormais correct — après COMMIT), immédiatement après `save_global_db` pour les 8
  qui utilisent la connexion request-scoped `Depends(get_conn)` (dont le COMMIT réel a lieu après le
  retour du handler — limite architecturale non résolue par ce correctif, mais sans régression par
  rapport à l'existant). Tests ajoutés : `save_global_db` ne peuple plus le cache
  (`test_save_global_db_does_not_touch_cache`), `set_cached_global` peuple bien le cache,
  `config.store.save_global` peuple le cache seulement après un commit réussi et **pas du tout** si
  le commit échoue (mocks purs, rouge→vert vérifié par `git stash`) ; suite complète (913 passés,
  171 échecs pré-existants identiques) sans régression sur `routes/admin.py`/`routes/test_vm.py`.

**Symptôme** : `save_global_db` positionne `_cache = cfg` **à l'intérieur** du bloc
`async with begin()`. Si le `COMMIT` échoue à la sortie du contexte, la DB rollback mais `_cache`
contient déjà la config **non commitée** → toutes les lectures suivantes (`get_cached_global`) servent
un état fantôme jusqu'au prochain `warm_global_cache` (redémarrage).

**Correction** : mettre à jour `_cache` seulement **après** le commit réussi (dans `store.save_global`,
après la sortie du `begin()`), pas dans la fonction DB.
