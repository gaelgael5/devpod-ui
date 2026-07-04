# 030 — Vault : master keys résidentes en mémoire au-delà de l'expiration du cookie

- **Sévérité** : mineur (fuite mémoire + surface d'exposition d'une clé qui devrait être éphémère)
- **Sous-système** : vault
- **Fichiers** : `vault/session.py:3-19` (dict global `_sessions`), `app.py:298` (`max_age=86400`)
- **Statut** : corrigé — `_sessions` stocke désormais `(master_key, expires_at)`, avec
  `_SESSION_TTL_S = 86400` aligné sur `max_age` du cookie (`app.py`). `get_master_key`/
  `is_unlocked` évincent paresseusement une entrée expirée (jamais renvoyée), et
  `set_master_key` balaie en plus toutes les sessions expirées à chaque nouvel unlock — borne la
  mémoire même pour des sessions abandonnées jamais relues. Tests ajoutés : expiration de
  `get_master_key`/`is_unlocked` après le TTL, éviction réelle du dict (pas juste masquée), balayage
  déclenché par un nouvel unlock — rouge→vert vérifié par `git stash`.

**Symptôme** : `_sessions` n'est purgé qu'au `logout` explicite ou au `reset_vault`. Le cookie expire à
24 h, mais si l'utilisateur ne se déconnecte pas, la master key déchiffrée reste **indéfiniment** en RAM
sous l'ancien `session_id`.

**Correction** : TTL / éviction sur `_sessions`, aligné sur `max_age` du cookie.
