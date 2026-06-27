# Plan — Auth OAuth 2.1 de la passerelle MCP (gateway = AS maison)

> Spec : `docs/superpowers/specs/2026-06-26-mcp-gateway-oauth-design.md`. AS **maison** (tokens opaques, PKCE S256). Branche `dev`. TDD, commits fréquents. Docker absent en local → les tests purs tournent ; les tests DB/route sont validés en CI/serveur.

**Goal :** permettre à Claude web (OAuth only) de se connecter à `/mcp` via un flow OAuth 2.1 dont la gateway est l'Authorization Server, le consentement réutilisant l'écran de grants.

**Tech :** Python 3.12 + FastAPI + pydantic v2 + SQLAlchemy Core async + Postgres ; React/TS pour le consentement. Tokens opaques `mcpk_` (= apikey, `kind=oauth`). `joserfc` dispo (pas requis : pas de JWT).

## Global Constraints
- `extra="forbid"` sur les modèles pydantic ; `from __future__ import annotations`.
- Secrets jamais loggés ; tokens/refresh/codes stockés **hashés SHA256**, jamais en clair.
- PKCE **S256 obligatoire** ; pas de flow implicite ; `redirect_uri` validée contre le client.
- Tout sur `dev`, jamais `main`.

---

## Lot 1 — Migration + tables + accesseurs DB

**Fichiers :**
- Create `backend/alembic/versions/027_mcp_oauth.py` (revision="027", down_revision="026").
- Modify `backend/src/portal/db/tables.py` : tables `mcp_oauth_client`, `mcp_oauth_authcode` ; colonnes `mcp_apikey` (`kind`,`client_id`,`refresh_token_hash`,`expires_at`).
- Create `backend/src/portal/db/oauth.py` : accesseurs.
- Test `backend/tests/db/test_oauth_db.py` (skip si pas de DB).

**Interfaces produites (`db/oauth.py`) :**
- `insert_client(conn, *, client_id, redirect_uris: list[str], client_name, metadata: dict) -> None`
- `get_client(conn, client_id) -> dict|None`
- `insert_authcode(conn, *, code_hash, client_id, owner_login, redirect_uri, code_challenge, scope, grants: list[dict], expires_at) -> None`
- `consume_authcode(conn, code_hash) -> dict|None` (retourne et marque `used=true` atomiquement ; None si absent/used/expiré)
- `find_apikey_by_refresh_hash(conn, refresh_hash) -> dict|None`

Tables : suivre le pattern §5 de la spec (Core `Table()`, `JSONB` pour `metadata`/`grants`/`redirect_uris`).

---

## Lot 2 — Helpers PKCE & génération (purs, testables hors DB)

**Fichiers :**
- Create `backend/src/portal/oauth/pkce.py` : `verify_s256(verifier: str, challenge: str) -> bool` = `base64url_nopad(sha256(verifier)) == challenge`.
- Create `backend/src/portal/oauth/tokens.py` : `new_secret(prefix) -> str` (prefix + token_urlsafe(32)), `sha256_hex(s) -> str`, `new_client_id() -> str`.
- Test `backend/tests/oauth/test_pkce.py`, `test_tokens.py`.

**Tests clés :** verifier/challenge valides → True ; challenge falsifié → False ; verifier vide → False. `new_secret("mcpk_")` commence par `mcpk_` et est unique.

---

## Lot 3 — Service OAuth (logique, sans HTTP)

**Fichiers :**
- Create `backend/src/portal/oauth/service.py`.
- Test `backend/tests/oauth/test_oauth_service.py`.

**Interfaces produites :**
- `register_client(conn, redirect_uris, client_name) -> dict` (crée `mcp_oauth_client` public).
- `make_authcode(conn, *, client_id, owner_login, redirect_uri, code_challenge, scope, grants) -> str` (retourne le code clair, stocke le hash + TTL 5 min).
- `exchange_code(conn, *, code, client_id, redirect_uri, code_verifier) -> dict` : consomme le code, vérifie PKCE + redirect_uri + client, **crée une `mcp_apikey kind=oauth`** + ses grants (depuis `authcode.grants`, via `db.set_grant`) + un refresh token ; retourne `{access_token, refresh_token, token_type:"Bearer", expires_in:null}`.
- `refresh(conn, *, refresh_token, client_id) -> dict` : rotation (révoque l'ancien, émet un nouveau couple).
- Erreurs typées (`OAuthError(code, description)`) → mappées en réponses RFC 6749 par les routes.

**Tests clés :** code échangé → apikey kind=oauth créée avec les bons grants ; PKCE invalide → erreur `invalid_grant` ; redirect_uri ≠ enregistré → erreur ; code réutilisé → erreur ; refresh → ancien invalidé.

---

## Lot 4 — Découverte + DCR + /token

**Fichiers :**
- Create `backend/src/portal/routes/oauth.py` (router, prefix `""` monté à la racine pour `/.well-known` et `/oauth`).
- Modify `backend/src/portal/app.py` : `include_router(oauth_router)`.
- Test `backend/tests/routes/test_oauth_routes.py`.

**Endpoints :**
- `GET /.well-known/oauth-protected-resource` → `{resource: f"{external_url}/mcp", authorization_servers:[external_url]}`.
- `GET /.well-known/oauth-authorization-server` → métadonnées (issuer, endpoints, `S256`, grants, `token_endpoint_auth_methods_supported:["none"]`).
- `POST /oauth/register` (DCR) → `register_client` → `{client_id, redirect_uris, token_endpoint_auth_method:"none", ...}` (201).
- `POST /oauth/token` (form-encoded) → `authorization_code` ou `refresh_token` → `exchange_code`/`refresh`. Erreurs → JSON `{error, error_description}` + statut 400.

`external_url` = `load_global().server.external_url`.

---

## Lot 5 — /authorize + décision + wrapper ASGI 401

**Fichiers :**
- Modify `backend/src/portal/routes/oauth.py` : `GET /oauth/authorize`, `POST /oauth/authorize/decision`.
- Create `backend/src/portal/mcp/asgi_auth.py` : middleware ASGI `BearerGate` devant le mount `/mcp`.
- Modify `backend/src/portal/app.py` : envelopper le mount `/mcp` avec `BearerGate`.
- Test `backend/tests/routes/test_oauth_authorize.py`, `backend/tests/mcp/test_asgi_auth.py`.

**Flux `/authorize` :**
- Valider params (`client_id` existe, `redirect_uri` ∈ client, `response_type=code`, `code_challenge`+`S256`, `state`).
- Session portail absente (`get_current_user` None) → 302 `/auth/login?next=<authorize url>`.
- Présente → persiste la requête validée sous un `request_id` (table `mcp_oauth_authcode` partiel ou cache court) et **302 vers la SPA `/oauth/consent?request_id=…`**.
- `POST /oauth/authorize/decision {request_id, approve, grants}` (session requise) → si approve : `make_authcode(grants)` → renvoie `{redirect: redirect_uri?code=…&state=…}` ; la SPA y redirige.

**`BearerGate` (ASGI) :** lit `Authorization`, `resolve_tenant`. Si None/expiré → réponse **401** `WWW-Authenticate: Bearer resource_metadata="{external_url}/.well-known/oauth-protected-resource"`. Sinon `await app(scope, receive, send)`.

**Tests clés :** `/authorize` sans session → 302 login ; avec session → 302 consent ; decision approve → code émis ; `BearerGate` sans token → 401+header ; avec apikey valide → passe.

---

## Lot 6 — Frontend écran de consentement

**Fichiers :**
- Create `frontend/src/features/oauth/ConsentPage.tsx` (route `/oauth/consent`).
- Create `frontend/src/features/oauth/useConsent.ts` (charge la requête via `request_id`, POST decision).
- Modify `frontend/src/router.tsx` : route `/oauth/consent` (RequireAuth, hors AppShell).
- Reuse le composant de grants (`GrantEditor`/`GrantRow` de `features/mcp`) pour choisir backends + curation.
- i18n fr/en. Test `ConsentPage.test.tsx` (MSW).

**Backend support :** `GET /oauth/consent-request/{request_id}` → `{client_name, scope}` (infos à afficher). La décision réutilise `POST /oauth/authorize/decision`.

---

## Lot 7 — Validation d'entrée étendue

**Fichiers :**
- Modify `backend/src/portal/mcp/dispatch_common.py` : `resolve_tenant` rejette si `expires_at` dépassé (déjà géré au Lot 5 via BearerGate, mais garder cohérent dans les handlers).
- Modify `backend/src/portal/db/mcp.py` : `find_apikey_by_hash` inclut `expires_at`/`kind`.
- Test : token oauth expiré → refusé ; apikey statique → toujours OK (non-régression).

---

## Lot 8 — Déploiement + E2E

- Migration appliquée au démarrage (run_migrations au lifespan, déjà en place).
- Rebuild image portail + restart sur la VM.
- E2E côté serveur (script) : DCR → authorize (cookie session) → token → `/mcp` avec le token → primitive OK.
- Guider l'utilisateur pour ajouter le connecteur dans Claude web (URL `https://dev.yoops.org/mcp`).

---

## Self-review (couverture spec)
- §4 endpoints → Lots 4-5. §5 modèle → Lot 1. §6 consentement → Lots 5-6. §7 validation → Lots 5,7. §8 sécurité → PKCE Lot 2, redirect_uri Lot 3, session Lot 5, hash partout. §9 tests → chaque lot. §3 flux → Lots 4-5-7.
