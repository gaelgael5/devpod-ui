# Écran admin de configuration OIDC — design

**Date** : 2026-06-24
**Statut** : validé (brainstorming), prêt à implémenter

## Problème

Permettre à un admin de saisir/modifier la configuration OIDC (`issuer`/URL,
`client_id`, `client_secret`) depuis un écran dédié, sans exposer le secret.

Le `GET /admin/config` existant renvoie tout le `GlobalConfig` **secret compris** — on
ne construit pas dessus pour cette feature.

## Backend (endpoints dédiés)

- **`GET /admin/oidc`** (require_admin) → `{issuer, client_id, has_secret: bool}`.
  Ne renvoie **jamais** la valeur du secret.
- **`PUT /admin/oidc`** (require_admin) → body `{issuer, client_id, client_secret?}` :
  - `client_secret` vide/absent → **on conserve** le secret existant ;
  - sinon → on le remplace.
  - Les autres réglages OIDC (`scopes`, `role_claim`, `admin_role`, `user_role`,
    `username_claim`) sont **préservés** (`OidcConfig.model_copy(update=…)`).
  - Persiste via `save_global_db`.

## Frontend

- Écran **`AdminOidc`** : route `/admin/oidc` sous `AdminGuard` + entrée de navigation.
- Formulaire : `issuer` (URL), `client_id`, `client_secret` (champ password ;
  placeholder « (inchangé) », vide = conserver). Bouton Enregistrer → toast.
- **Note d'avertissement** : modifier ces valeurs affecte l'authentification ; un
  réglage erroné peut bloquer les prochains logins.
- Hook `useAdminOidc` (GET) + `useSaveOidc` (PUT).
- i18n fr + en (`admin.oidc.*`).

## Hors périmètre

- Édition des autres réglages OIDC (scopes, claims…) — restent figés.
- Validation live de la connexion OIDC (test de l'issuer).

## Tests

- Backend : `GET` ne contient pas `client_secret` et expose `has_secret` ;
  `PUT` sans secret le préserve, `PUT` avec secret le remplace (mock conn).
- Front : l'écran rend le formulaire pré-rempli (Vitest).
