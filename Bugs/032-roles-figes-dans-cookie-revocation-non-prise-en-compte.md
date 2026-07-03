# 032 — Rôles figés dans le cookie de session — révocation Keycloak non prise en compte

- **Sévérité** : mineur (par-design partiel ; fenêtre de 24 h)
- **Sous-système** : auth
- **Fichiers** : `auth/rbac.py:72-80`, `auth/router.py:140`, `auth/router.py:258-262`
- **Statut** : ouvert

**Symptôme** : les rôles sont capturés à la connexion et stockés dans le cookie signé. `caddy_verify` et
`require_admin` les relisent depuis la session, jamais depuis l'IdP. Un utilisateur dé-privilégié côté
Keycloak conserve ses accès (y compris admin) jusqu'à l'expiration du cookie (24 h).

**Correction** : TTL de session plus court, ou revérification périodique des rôles auprès de l'IdP.
Documenter le compromis si conservé.
