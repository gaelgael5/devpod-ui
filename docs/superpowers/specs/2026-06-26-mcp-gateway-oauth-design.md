# Spec — Authentification OAuth 2.1 de la passerelle MCP

Date : 2026-06-26
Statut : design validé (brainstorming)
Périmètre : un seul lot fonctionnel (l'auth OAuth de la gateway), découpé en étapes pour l'implémentation.

## 1. Contexte & objectif

La passerelle MCP (`/mcp`, Streamable HTTP) n'accepte aujourd'hui qu'une **apikey statique** `mcpk_…` en `Authorization: Bearer` (hash SHA256 → `mcp_apikey` → grants via `mcp_apikey_grant`).

**Claude web (claude.ai)** ne sait pas utiliser un Bearer statique : son UI de connecteur custom n'accepte **que l'OAuth 2.1** (flow Authorization Code + PKCE, avec découverte et enregistrement dynamique). Limitation côté Anthropic confirmée (pas de champ « static bearer » / header custom).

Objectif : permettre à Claude web de se connecter à la gateway **sans gérer d'utilisateurs dans Keycloak** (qui ne fait que brokeriser Google) et **sans coupler** la gateway à un IdP externe.

Solution retenue : **la gateway devient son propre Authorization Server** (via Authlib). Keycloak/Google ne servent qu'à **prouver l'identité de l'admin au moment du consentement** (session du portail), pas à délivrer le token MCP.

## 2. Décisions de conception (actées)

| # | Décision | Choix |
|---|---|---|
| D1 | apikey statique vs OAuth | **Les deux en parallèle** : la gateway accepte un Bearer apikey **ou** un Bearer token OAuth |
| D2 | Format du token OAuth | **Opaque = une apikey** : stocké comme une ligne `mcp_apikey` (hash + grants). `resolve_tenant` réutilisé tel quel |
| D3 | Consentement | **Choix à la volée** : l'utilisateur coche backends + curation via l'écran de grants existant ; ces grants sont liés au token émis |
| D4 | Enregistrement client | **DCR** (RFC 7591) : Claude s'enregistre seul en **client public** (PKCE, pas de secret) |
| D5 | Implémentation AS | **Authlib** (déjà dépendance du projet) gère PKCE, authorization_code, refresh, validation `redirect_uri`, expiration |
| D6 | Durée de vie du token | **Access token long‑lived, révocable** (comme une apikey) + **refresh_token** pour la conformité OAuth (rotation à la demande) |

## 3. Architecture & flux

La gateway joue deux rôles sur le portail FastAPI :
- **Authorization Server** : émet les tokens (endpoints OAuth + DCR + découverte).
- **Resource Server** : valide le Bearer à l'entrée `/mcp` (inchangé, étendu pour les tokens OAuth).

Flux complet pour Claude web :

```
Claude ──▶ GET /mcp (sans token)
        ◀── 401 + WWW-Authenticate: Bearer resource_metadata="…/.well-known/oauth-protected-resource"
Claude ──▶ GET /.well-known/oauth-protected-resource     (RFC 9728 → annonce l'AS)
Claude ──▶ GET /.well-known/oauth-authorization-server   (RFC 8414 → endpoints, S256)
Claude ──▶ POST /oauth/register                          (RFC 7591 → client_id public)
Claude ──▶ GET /oauth/authorize?client_id&redirect_uri&code_challenge&state&response_type=code
                 │  session portail absente → 302 login OIDC habituel (?next=…)
                 │  session présente → écran de consentement (grants)
        ◀────────┘ 302 redirect_uri?code=…&state=…
Claude ──▶ POST /oauth/token (grant_type=authorization_code, code, code_verifier, client_id)
        ◀── { access_token, token_type:"Bearer", refresh_token, expires_in }
Claude ──▶ POST /mcp (Authorization: Bearer <access_token>)  ──▶ backends autorisés
```

Issuer = `https://dev.yoops.org` (URL publique du portail). Ressource protégée = `https://dev.yoops.org/mcp`. Endpoints OAuth sous `/oauth/…`, métadonnées sous `/.well-known/…`. Ce sont des **routes FastAPI classiques** (le `/mcp` reste un mount ASGI Streamable HTTP distinct).

## 4. Endpoints OAuth & découverte (Authlib)

- `GET /.well-known/oauth-protected-resource` (RFC 9728) : `{ resource, authorization_servers: ["https://dev.yoops.org"] }`.
- `GET /.well-known/oauth-authorization-server` (RFC 8414) : `issuer`, `authorization_endpoint`, `token_endpoint`, `registration_endpoint`, `response_types_supported=["code"]`, `grant_types_supported=["authorization_code","refresh_token"]`, `code_challenge_methods_supported=["S256"]`, `token_endpoint_auth_methods_supported=["none"]`.
- `POST /oauth/register` (RFC 7591, DCR) : entrée `{ redirect_uris, client_name?, … }` → crée un `mcp_oauth_client` **public** → retourne `{ client_id, redirect_uris, token_endpoint_auth_method:"none", … }`. Pas de `client_secret`.
- `GET /oauth/authorize` : validé par Authlib (`client_id`, `redirect_uri` ∈ client, `response_type=code`, `code_challenge` + `S256`, `state`). Exige la session portail. Sert l'écran de consentement.
- `POST /oauth/token` : `authorization_code` (code + `code_verifier` + `redirect_uri` + `client_id`, PKCE vérifié par Authlib) **ou** `refresh_token`. Émet l'access token (= une `mcp_apikey kind=oauth`) et un refresh token.

Le `WWW-Authenticate` est ajouté sur les réponses 401 de `/mcp` pour amorcer la découverte côté Claude.

## 5. Modèle de données (migration Alembic)

Nouvelles tables :

```sql
CREATE TABLE mcp_oauth_client (
    client_id   text PRIMARY KEY,            -- généré (public, PKCE)
    redirect_uris text NOT NULL,             -- JSON array
    client_name text NOT NULL DEFAULT '',
    metadata    text NOT NULL DEFAULT '{}',  -- DCR brut (JSON)
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE mcp_oauth_authcode (
    code            text PRIMARY KEY,         -- hash du code (jamais en clair)
    client_id       text NOT NULL REFERENCES mcp_oauth_client(client_id) ON DELETE CASCADE,
    owner_login     text NOT NULL REFERENCES users(login),
    redirect_uri    text NOT NULL,
    code_challenge  text NOT NULL,
    code_challenge_method text NOT NULL DEFAULT 'S256',
    scope           text NOT NULL DEFAULT '',
    grants          text NOT NULL DEFAULT '[]', -- backends + curation choisis au consentement (JSON)
    expires_at      timestamptz NOT NULL,      -- TTL court (quelques minutes)
    used            boolean NOT NULL DEFAULT false
);
```

Extension de `mcp_apikey` (le token OAuth **est** une apikey) :

```sql
ALTER TABLE mcp_apikey ADD COLUMN kind text NOT NULL DEFAULT 'apikey';   -- 'apikey' | 'oauth'
ALTER TABLE mcp_apikey ADD COLUMN client_id text NULL REFERENCES mcp_oauth_client(client_id) ON DELETE SET NULL;
ALTER TABLE mcp_apikey ADD COLUMN refresh_token_hash text NULL;
ALTER TABLE mcp_apikey ADD COLUMN expires_at timestamptz NULL;            -- NULL = pas d'expiration (D6)
```

Les **grants** restent dans `mcp_apikey_grant` **sans changement** : à l'émission du token (`/oauth/token`), on crée la ligne `mcp_apikey (kind='oauth')` puis on transfère `mcp_oauth_authcode.grants` → lignes `mcp_apikey_grant`. Le préfixe du secret reste `mcpk_` (même génération, même hash) ; seul `kind` distingue l'origine.

## 6. Écran de consentement (réutilise les grants)

`GET /oauth/authorize`, session portail présente :
1. Le backend persiste la requête d'autorisation (paramètres validés Authlib) sous un `request_id` court.
2. Redirige le navigateur vers la route SPA `/oauth/consent?request_id=…`.
3. La SPA affiche : le nom du client (« Claude »), et **le composant de grants existant** (choisir backends + curation d'outils).
4. À la validation : `POST /oauth/authorize/decision { request_id, approve, grants }`.
5. Le backend (Authlib) génère le `code` (avec `grants` dans `mcp_oauth_authcode`) et renvoie la `redirect_uri?code=…&state=…` ; la SPA redirige le navigateur dessus.

Si l'utilisateur n'est pas connecté au portail à l'étape `GET /oauth/authorize` → redirection vers le login OIDC habituel avec `next` pour revenir.

## 7. Validation à l'entrée `/mcp`

Deux niveaux, pour respecter la découverte OAuth (qui exige un **401 HTTP**, alors que les handlers MCP actuels renvoient une `McpError` dans un corps JSON-RPC en HTTP 200) :

**a) Niveau transport — wrapper ASGI devant le mount `/mcp`.** Nouveau composant placé avant `StreamableHTTPASGIApp`. Il lit le `Authorization: Bearer` et résout le tenant (`resolve_tenant`). Si le token est **absent, invalide ou expiré** → il court-circuite et renvoie **`401` HTTP + `WWW-Authenticate: Bearer resource_metadata="…/.well-known/oauth-protected-resource"`**, ce qui amorce le flow OAuth côté Claude. Sinon il passe la main au mount MCP (le tenant résolu peut être propagé via le scope ASGI pour éviter un double lookup).

**b) Niveau primitive — handlers MCP (inchangé).** Avec un token valide, un appel sur un backend/outil **non accordé** continue de renvoyer une `McpError` granulaire (le wrapper n'a vérifié que l'authentification, pas l'autorisation fine).

`resolve_tenant` : **un seul lookup** par `token_hash` dans `mcp_apikey` (le token OAuth y est, `kind='oauth'`) ; en plus de l'existant (`revoked=false`), rejeter si `expires_at` est dépassé. Aucune divergence apikey vs OAuth dans la résolution des droits : tous deux pointent vers `owner_login` + `mcp_apikey_grant`.

## 8. Sécurité

- **PKCE S256 obligatoire** (Authlib) ; pas de flow implicite.
- `redirect_uri` validée contre celles enregistrées au DCR.
- Le consentement **exige la session du portail** (OIDC) → c'est bien l'admin qui accorde.
- Tokens **opaques, hashés** en DB (jamais en clair), **révocables** instantanément (`revoked`).
- `authorization_code` : usage unique (`used`), TTL court, lié au `client_id` + `code_challenge`.
- `refresh_token` haché, rotation à chaque usage (Authlib).
- DCR ouvert (clients publics) : acceptable car aucun droit n'est accordé sans le consentement authentifié ; le client_id seul ne donne accès à rien.
- L'admin OAuth (`/oauth/register`, `/authorize`) passe par le tunnel Cloudflare → HTTPS de bout en bout.

## 9. Tests

- `POST /oauth/register` → client public créé, pas de secret.
- Découverte : `/.well-known/*` renvoient les bons champs (S256, endpoints).
- Flow `authorization_code` complet avec PKCE (challenge/verifier) → access + refresh.
- PKCE invalide / `redirect_uri` non enregistrée → rejet.
- Consentement → les `grants` choisis se retrouvent exactement sur le token (`mcp_apikey_grant`).
- `refresh_token` → rotation, ancien refresh invalidé.
- Entrée `/mcp` : accepte apikey `mcpk_` **et** token OAuth ; rejette token expiré/révoqué avec `WWW-Authenticate`.
- Non-régression : les apikeys statiques existantes fonctionnent toujours.

## 10. Découpage prévisionnel (pour writing-plans)

1. **Migration** : tables `mcp_oauth_client`, `mcp_oauth_authcode` + colonnes `mcp_apikey`.
2. **AS Authlib** : intégration (models client/token/authcode), `/oauth/token`, validation PKCE.
3. **Découverte & DCR** : `/.well-known/*`, `/oauth/register`, `WWW-Authenticate` sur `/mcp`.
4. **Consentement** : `/oauth/authorize` + route SPA `/oauth/consent` réutilisant l'écran de grants + `/oauth/authorize/decision`.
5. **Validation d'entrée** : `resolve_tenant` étendu (expiration), erreurs avec `WWW-Authenticate`.
6. **E2E** : test du flow complet contre Claude web (via le tunnel).

## 11. Hors périmètre (YAGNI)

- Profils MCP (`mcp_profile`) et mapping rôles Keycloak → profils (évolution multi‑tenant ultérieure).
- Validation de JWT Keycloak entrant côté gateway (on ne délègue pas l'auth MCP à Keycloak).
- Scopes OAuth granulaires côté protocole (la granularité passe par les grants, pas par des scopes standardisés).
- Expiration courte forcée des access tokens (cf. D6 : long‑lived révocable).
