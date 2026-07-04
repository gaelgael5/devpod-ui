# 031 — Vault : `session_id` vide non rejeté (clé partagée si l'invariant casse)

- **Sévérité** : mineur (non exploitable aujourd'hui ; défaut de fail-closed)
- **Sous-système** : vault
- **Fichiers** : `vault/session.py`, `routes/vault.py:42-43` (`_sid` → `""` par défaut)
- **Statut** : corrigé — `_sid` (routes/vault.py) fail-closed : lève `HTTPException(401)` si
  `session_id` est absent ou vide, au lieu de renvoyer `""`. Défense en profondeur dans
  `vault/session.py` : `set_master_key("", ...)` lève `ValueError`, `get_master_key`/`is_unlocked`
  traitent `""` comme toujours absent/verrouillé — même si un futur appelant contournait `_sid`.
  Tests ajoutés : `_sid` renvoie 401 sur absent/vide, `set_master_key` rejette `""`, `get_master_key`/
  `is_unlocked` sur `""` — rouge→vert vérifié par `git stash` (la reproduction confirme le risque
  décrit : sur le code non corrigé, deux appels successifs à `set_master_key("", ...)` partagent
  bien la même entrée `_sessions[""]`).

**Symptôme** : `_sid` renvoie `""` si `session_id` est absent de la session. L'invariant tient
aujourd'hui (`setdefault("session_id", ...)` posé avant `session["user"]` dans `local_login` et
`callback`). Mais rien ne fail-closed : un futur chemin d'auth qui oublierait le `setdefault` ferait que
**tous ces utilisateurs partagent la clé `_sessions[""]`**.

**Correction** : refuser toute opération vault si `session_id` est vide, plutôt que d'indexer sur `""`.
