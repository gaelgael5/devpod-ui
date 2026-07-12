# 032 — Rôles figés dans le cookie de session — révocation Keycloak non prise en compte

- **Sévérité** : mineur (par-design partiel ; fenêtre de 24 h)
- **Sous-système** : auth
- **Fichiers** : `auth/rbac.py:72-80`, `auth/router.py:140`, `auth/router.py:258-262`
- **Statut** : corrigé — TTL de session configurable (`session_max_age`, défaut 3600 s) servant à la fois d'idle timeout (max_age du cookie) et de plafond d'âge **absolu** depuis le login (`session["auth_time"]` posé au login, comparé dans `rbac.get_current_user`). Le plafond absolu est nécessaire parce que le `max_age` de Starlette est **glissant** (cookie réémis à chaque réponse) : sans lui, seules les sessions inactives expireraient et un utilisateur actif garderait ses rôles figés indéfiniment. À l'expiration → session traitée comme non authentifiée → re-login OIDC → rôles rafraîchis depuis Keycloak. Fail-closed : `auth_time` absent (cookie legacy) = expiré. Chemin Bearer `portal_api_key` non impacté.
  **Renfort ajouté à la relecture** : le contrôle a été factorisé en `rbac.session_within_max_age(session)` car 4 endpoints proxy authentifient **hors** du dep RBAC en lisant `session["user"]` en direct — `vscode_proxy.py` (le proxy openvscode qui, depuis Option A, fait lui-même l'auth : « L'authentification est vérifiée ici »), sa variante WebSocket, `workspace_ssh.py` et `ssh_proxy.py`. Sans ce renfort, l'accès VS Code/SSH aurait **survécu au plafond** (cookie glissant) — trou fail-closed. Les 4 sites appliquent désormais `session_within_max_age`. Tests ajoutés : `test_session_expiry.py` (helper + `test_vscode_proxy_session_login_enforces_absolute_cap`, rouge→vert).
  **Risque résiduel noté** (hors périmètre) : `vault/session.py:_SESSION_TTL_S = 86400` est en dur, « aligné sur le max_age cookie » ; avec le défaut abaissé à 3600 s, la master key en RAM peut survivre plus longtemps que la session — à réaligner (lié bug 030).

**Symptôme** : les rôles sont capturés à la connexion et stockés dans le cookie signé. `caddy_verify` et
`require_admin` les relisent depuis la session, jamais depuis l'IdP. Un utilisateur dé-privilégié côté
Keycloak conserve ses accès (y compris admin) jusqu'à l'expiration du cookie (24 h).

**Correction** : TTL de session plus court, ou revérification périodique des rôles auprès de l'IdP.
Documenter le compromis si conservé.
