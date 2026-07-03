# 031 — Vault : `session_id` vide non rejeté (clé partagée si l'invariant casse)

- **Sévérité** : mineur (non exploitable aujourd'hui ; défaut de fail-closed)
- **Sous-système** : vault
- **Fichiers** : `vault/session.py`, `routes/vault.py:42-43` (`_sid` → `""` par défaut)
- **Statut** : ouvert

**Symptôme** : `_sid` renvoie `""` si `session_id` est absent de la session. L'invariant tient
aujourd'hui (`setdefault("session_id", ...)` posé avant `session["user"]` dans `local_login` et
`callback`). Mais rien ne fail-closed : un futur chemin d'auth qui oublierait le `setdefault` ferait que
**tous ces utilisateurs partagent la clé `_sessions[""]`**.

**Correction** : refuser toute opération vault si `session_id` est vide, plutôt que d'indexer sur `""`.
