# 030 — Vault : master keys résidentes en mémoire au-delà de l'expiration du cookie

- **Sévérité** : mineur (fuite mémoire + surface d'exposition d'une clé qui devrait être éphémère)
- **Sous-système** : vault
- **Fichiers** : `vault/session.py:3-19` (dict global `_sessions`), `app.py:298` (`max_age=86400`)
- **Statut** : ouvert

**Symptôme** : `_sessions` n'est purgé qu'au `logout` explicite ou au `reset_vault`. Le cookie expire à
24 h, mais si l'utilisateur ne se déconnecte pas, la master key déchiffrée reste **indéfiniment** en RAM
sous l'ancien `session_id`.

**Correction** : TTL / éviction sur `_sessions`, aligné sur `max_age` du cookie.
