# 033 — Construction de chemin sous `/data` sans `safe_user_path`

- **Sévérité** : mineur (mitigé par `validate_username` en amont ; viole une règle non négociable)
- **Sous-système** : config / db
- **Fichiers** : `db/user_config.py:44` (`_data_root() / "users" / login / "config.yaml"`) ; même motif `devpod/service.py:493`, `routes/workspace_ops.py:671` (`_data_root() / "logs" / login`)
- **Statut** : ouvert

**Symptôme** : `login` est injecté directement comme segment de chemin. Non exploitable aujourd'hui
(`login` validé par `validate_username`), mais `CLAUDE.md` impose que **toute** construction de chemin
sous `/data` passe par `safe_user_path`, précisément pour ne pas dépendre de la validation d'un appelant.

**Correction** : router ces constructions via `safe_user_path(login, "config.yaml")` / `(login, "logs")`.
