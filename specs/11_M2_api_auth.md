# M2 — API, OIDC Keycloak, RBAC, provisioning user

**Objectif :** application FastAPI avec authentification OIDC contre Keycloak, création du répertoire
utilisateur au premier login, et contrôle d'accès dev/admin. Pas encore de DevPod.

## Prérequis
- M1 livré. Client Keycloak `workspace-portal` créé dans le realm `yoops` (confidential, redirect
  URI `https://dev.yoops.org/auth/callback`). Rôles realm `dev` et `admin`.

## Étapes

### M2.1 — App + settings
- `app.py` : FastAPI, montage des routers, middleware de session (cookie signé).
- `pydantic-settings` lit `.env` (OIDC_CLIENT_SECRET, clé de session, etc.). Ne jamais commiter `.env`.

### M2.2 — OIDC (`auth/oidc.py`) avec authlib
- Flow code + PKCE + state + nonce.
- Découverte via `issuer/.well-known/openid-configuration`.
- **Validation ID token** : signature contre JWKS (cache + refetch sur `kid` inconnu), `iss`, `aud`,
  `exp`/`iat` avec leeway. Pièges §C-16.
- Endpoints : `/auth/login`, `/auth/callback`, `/auth/logout`.

### M2.3 — RBAC (`auth/rbac.py`)
- Extraire rôles via le chemin `auth.oidc.role_claim` (ex. `realm_access.roles`). Piège §C-17.
- Dépendances FastAPI : `require_user`, `require_admin`. User sans rôle connu → 403 propre.
- `username` depuis `username_claim`. Valider qu'il matche `^[a-z0-9][a-z0-9._-]{0,38}[a-z0-9]$`
  (utilisé comme nom de répertoire — piège §C-18).

### M2.4 — Provisioning au premier login
- Au callback, si `users/<login>/` absent : `ensure_user_dir` + créer `config.yaml` initial avec un
  `secret_ns` = `uuid4()`. **Le GUID ne doit jamais être dérivé du login** (piège : un login
  réutilisé hériterait du coffre d'un ancien user). 
- Idempotent : un user existant ne voit pas son `secret_ns` régénéré.

### M2.5 — Endpoints de paramétrage (CRUD config, sans exécution)
- `GET/PUT /me/config` (scope user, validé pydantic).
- `GET/POST/DELETE /me/workspaces` : éditent la liste `workspaces` du user (pas de `up` encore).
- `GET/PUT /admin/config`, `GET/POST /admin/hosts` (require_admin).
- Toute écriture passe par `save_user`/`save_global` (atomique).

## Tests
- Callback OIDC simulé (token signé par une clé de test) : user créé, `secret_ns` UUID, dossier en place.
- Re-login : pas de régénération du `secret_ns`.
- RBAC : `dev` refusé sur `/admin/*` (403) ; `admin` accepté.
- Login invalide (claim username non conforme) → 403, pas de dossier créé.
- PUT config avec champ inconnu → 422 (extra=forbid remonte proprement).

## Definition of Done
- DoD commune + tests verts + un parcours manuel documenté (login réel Keycloak → dossier user créé).

## Pièges spécifiques M2
- §C-16 (validation OIDC complète, pas juste décoder le JWT), §C-17 (claim rôles imbriqué),
  §C-18 (login comme nom de dossier), §C-19 (flags cookie).
- Piège : ne pas faire confiance à `email`/`preferred_username` pour l'autorisation sans vérifier la
  signature et `aud`/`iss`. Un token d'un autre client du realm ne doit pas être accepté.
