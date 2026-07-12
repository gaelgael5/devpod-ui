# 033 — Construction de chemin sous `/data` sans `safe_user_path`

- **Sévérité** : mineur (mitigé par `validate_username` en amont ; viole une règle non négociable)
- **Sous-système** : config / db
- **Fichiers** : `db/user_config.py:44` (`_data_root() / "users" / login / "config.yaml"`) ; même motif `devpod/service.py:493`, `routes/workspace_ops.py:671` (`_data_root() / "logs" / login`)
- **Statut** : corrigé — `safe_user_path` factorisé sur une nouvelle `safe_login_path(root_name,
  login, *parts)` (racine paramétrable sous `_data_root()`, même validation regex + `is_relative_to`).
  `db/user_config.py::ensure_user_db` route désormais via `safe_user_path(login, "config.yaml")` ;
  `devpod/service.py::_log_path` et `routes/workspace_ops.py::get_workspace_logs` routent via
  `safe_login_path("logs", login, f"{ws_id}.log")` au lieu d'une concaténation de strings.
  Tests ajoutés pour `safe_login_path` (chemin correct, racine `users` équivalente à
  `safe_user_path`, rejet `..`/slash/login invalide) ; les tests existants de
  `test_workspace_logs.py` (4/4) passent inchangés après le refactor.

**Symptôme** : `login` est injecté directement comme segment de chemin. Non exploitable aujourd'hui
(`login` validé par `validate_username`), mais `CLAUDE.md` impose que **toute** construction de chemin
sous `/data` passe par `safe_user_path`, précisément pour ne pas dépendre de la validation d'un appelant.

**Correction** : router ces constructions via `safe_user_path(login, "config.yaml")` / `(login, "logs")`.
