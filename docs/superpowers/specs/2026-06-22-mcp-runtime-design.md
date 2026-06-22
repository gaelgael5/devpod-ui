# MCP Gateway — Runtime de fédération — Design

**Statut** : approuvé (brainstorming 2026-06-22)
**Spec amont** : `specs/23-mcp-gateway.md` (§8 comportement, §10 auth, §11 sécurité, §12 cycle de vie, §13 erreurs)
**Pré-requis** : lot 1 (registre `/me/mcp/*`, tables `mcp_backend`/`mcp_backend_key`/`mcp_apikey`/`mcp_apikey_grant`) livré.

---

## 1. Objet

Faire de la passerelle un **serveur MCP** (face aux clients, ex. Claude web) **et un client MCP** (face aux backends enregistrés), dans le **même process FastAPI** que le portail. Le lot 1 a posé le registre ; ce lot ajoute la **fédération réelle** : un client connecté à un point d'entrée unique voit et invoque les primitives (tools, resources, prompts) de tous les backends que ses grants autorisent.

## 2. Décisions actées (brainstorming)

1. **SDK** : SDK officiel `mcp` (PyPI `mcp`) pour le serveur ET le client, transport **Streamable HTTP** (+ `sse` en sortie). `stdio` rejeté au runtime (backends distants).
2. **Emplacement** : serveur MCP frontal **monté dans l'app FastAPI** du portail, sur la route `/mcp`. Endpoint unique, **multi-tenant** via l'apikey.
3. **Auth entrante** : **apikey uniquement** (Bearer `mcpk_…` → hash sha256 → owner). OIDC entrant **différé**.
4. **Secrets sortants** : clés `local` chiffrées avec une **KEK système** (`PORTAL_VAULT_KEK`), plus la master_key du PIN — la passerelle déchiffre en autonomie, sans session vault.
5. **Périmètre** : tools + resources + prompts + catalogue persistant + anti rug-pull + audit + notifications + santé/résilience.
6. **Hors périmètre (différés, notés)** : OIDC entrant ; résolution `harpocrate` au runtime (le token d'accès wallet dépend de la master_key de session ; au runtime seuls `local`(KEK), `none`, `${env://}` sont résolubles).

## 3. Périmètre

### Dans le périmètre
- Client MCP backend : `initialize`, `tools/list`, `tools/call`, `resources/list`, `resources/read`, `prompts/list`, `prompts/get`, abonnement `notifications/*_list_changed`.
- Gestionnaire de connexions backend (1 session/backend, lazy, pool, health check, reconnexion, timeout par appel).
- Catalogue persistant + épinglage anti rug-pull (quarantaine) + refresh (TTL + `list_changed`).
- Agrégation : owner → grants → backends `enabled` → catalogue → curation → namespacing → exclusion des quarantined.
- Serveur MCP frontal `/mcp` : `initialize` (instructions composées), `tools/`, `resources/`, `prompts/`, propagation des notifications, tool natif `gateway__list_backends`.
- Auth entrante apikey ; résolution secrets sortants KEK/none/env ; audit exhaustif.
- Migration du chiffrement des clés `local` du lot 1 vers la KEK système.

### Hors périmètre
- OIDC entrant ; `harpocrate` au runtime ; « code mode » ; fédération hiérarchique ; sampling/roots/elicitation.

## 4. Architecture

```
Client MCP ──Bearer apikey──> FastAPI : route /mcp  (serveur MCP frontal, SDK mcp)
                                  │  owner = lookup(hash(apikey)), non révoquée
                                  ├─ aggregator   : grants(owner) → catalogue → curation → namespacing
                                  ├─ connections  : 1 session cliente / backend (lazy, pool, health)
                                  │      └─ client MCP ──streamable_http/sse──> backend distant
                                  ├─ catalog      : mcp_tool_catalog (hash, quarantaine, refresh)
                                  ├─ runtime_secrets : résout la clé du grant (local-KEK / none / env)
                                  └─ audit        : mcp_audit_log
```

Endpoint unique `/mcp` ; l'apikey identifie l'owner et borne la vue (deny-by-default).

## 5. Modèle de données (migration 018)

### 5.1 `mcp_tool_catalog`
Cache des primitives par backend + épinglage anti rug-pull.

- `backend_id` text FK `mcp_backend(id)` ON DELETE CASCADE
- `kind` text CHECK in ('tool','resource','prompt')
- `original_name` text — nom/URI/identifiant original côté backend
- `definition` jsonb — définition telle que renvoyée par le backend
- `definition_hash` text — sha256 de `definition`
- `first_seen`, `last_seen` timestamptz
- `quarantined` boolean default false
- **PK (`backend_id`, `kind`, `original_name`)**

> **Écart assumé à la spec §5.3** : la spec utilise `namespaced_name` comme PK globale. En scope **par utilisateur**, deux owners peuvent enregistrer le même namespace (`rag`) → collision de `namespaced_name`. On scope donc le catalogue par `backend_id` (unique) ; le `namespaced_name` (`<backend.namespace>__<original_name>`) est **calculé à l'agrégation**, pas stocké comme clé.

### 5.2 `mcp_audit_log`
- `id` bigserial PK
- `ts` timestamptz default now()
- `apikey_id` text (nullable)
- `owner_login` text (nullable)
- `namespaced_name` text (nullable)
- `backend_id` text (nullable)
- `backend_key_id` text (nullable)
- `latency_ms` integer (nullable)
- `status` text NOT NULL — `ok | error | denied | timeout`
- `error` text (nullable)

> Pas de FK strictes sur l'audit (conservation même après suppression d'un backend/apikey).

## 6. Résolution des secrets sortants

`SecretResolver` runtime (étend la fondation du lot 1) résout la clé désignée par le grant :
- `storage_type='local'` → déchiffré avec la **KEK système** (cf. §7).
- backend public (`backend_key_id` null) → **aucun** bearer envoyé.
- référence `${env://NOM}` → `EnvSecretResolver` (lot 1).
- `harpocrate` / `${vault://}` → **non résoluble au runtime** (différé) ; un appel nécessitant une telle clé renvoie une erreur explicite et une ligne d'audit `error`.

La valeur claire n'est jamais journalisée ; elle n'existe qu'au point d'injection du bearer vers le backend, dans un type `Secret`.

## 7. Chiffrement KEK système (changement rétroactif lot 1)

`create_backend_key` (storage `local`) chiffrera désormais avec une clé dérivée de `PORTAL_VAULT_KEK` :
- `key = HKDF(SHA256, ikm=bytes.fromhex(PORTAL_VAULT_KEK), salt=None, info=b"mcp-backend-key-v1", length=32)`
- chiffrement AES-GCM via `vault/crypto.py` (`encrypt_token`/`decrypt_token`, qui prennent une clé 32 octets).

Conséquences :
- Créer une clé `local` **ne requiert plus** de session vault déverrouillée (`session_id`). La passerelle déchiffre au runtime, en autonomie.
- Aucune donnée à migrer (rien de déployé). On retire la dépendance `session_id` du chemin `local` de `create_backend_key`.
- `PORTAL_VAULT_KEK` absent → la création de clé `local` échoue proprement (déjà requis en prod par `app.py`).

## 8. Composants (modules `portal/mcp/`)

| Module | Responsabilité | Dépend de |
|---|---|---|
| `runtime_secrets.py` | KEK système (chiffre/déchiffre `local`) ; `RuntimeSecretResolver` (local/none/env) | `vault/crypto`, `settings`, `secrets/resolver` |
| `client.py` | Client MCP backend (SDK `mcp`) : initialize, tools/list, tools/call, resources/*, prompts/*, list_changed | SDK `mcp` |
| `connections.py` | Pool de sessions backend (lazy, 1/backend, health, reconnexion, timeout) | `client.py`, `db.mcp` |
| `catalog.py` | Sync catalogue → `mcp_tool_catalog`, `definition_hash`, quarantaine, refresh (TTL + list_changed) | `connections.py`, `db.mcp_catalog` |
| `aggregator.py` | owner → grants → backends enabled → catalogue → curation (expose_mode/expose — **note** : la curation par grant n'existe pas encore au lot 1, voir §12) → namespacing → exclusion quarantined | `db.mcp`, `catalog.py` |
| `server.py` | Serveur MCP frontal (SDK `mcp`, monté `/mcp`) : auth apikey, initialize, tools/, resources/, prompts/, notifications, `gateway__list_backends` | `aggregator.py`, `connections.py`, `runtime_secrets.py`, `db.mcp_audit` |
| `db/mcp_catalog.py`, `db/mcp_audit.py` | Accès SQLAlchemy Core aux 2 nouvelles tables | `db.tables` |

Montage dans `app.py` (lifespan : pré-charge les backends `enabled`, démarre le health check ; route `/mcp`).

## 9. Flux

### 9.1 `tools/list` (et resources/list, prompts/list)
1. apikey → owner (sinon 401/refus).
2. grants de l'owner ; pour chaque backend `enabled` : catalogue (refresh si TTL expiré ou `list_changed` reçu).
3. curation du grant (`expose_mode`/`expose`) — voir §12.
4. namespacing `original → <namespace>__<original>`.
5. exclure `quarantined`.
6. concaténer les tools natifs `gateway__*` ; retourner.

### 9.2 `tools/call`
1. découpe du nom namespacé sur le **premier** `__` → `(namespace, original)`.
2. owner → grant couvrant ce backend ET autorisant `original` (curation) ; sinon `denied` (sans révéler l'existence).
3. refus si `quarantined`.
4. résoudre la clé du grant (KEK/none/env) → session backend authentifiée (timeout).
5. forward `tools/call` avec `original` + arguments.
6. mapper résultat/erreur MCP (§13).
7. ligne d'audit (owner, apikey, backend, clé, tool namespacé, latence, statut).

### 9.3 resources & prompts
Même schéma : `resources/list`+`read`, `prompts/list`+`get`, namespacing des URIs/identifiants, routage par préfixe.

### 9.4 Notifications
À réception d'un `notifications/tools/list_changed` (resources/prompts) d'un backend : ré-agréger ce backend, mettre à jour le catalogue, puis émettre la notification vers les clients concernés.

## 10. Sécurité (§11)

| Menace | Mitigation |
|---|---|
| Rug pull | `definition_hash` épinglé ; au refresh, hash changé → `quarantined=true` jusqu'à approbation de l'**owner** (endpoint dédié) ; audit. |
| Tool poisoning | Descriptions backend = données non fiables, jamais exécutées ; changements journalisés. |
| Cross-server shadowing | Namespacing strict par `backend_id` ; un backend ne peut publier sous le préfixe d'un autre. |
| Fuite de credentials | Secrets résolus à la volée (KEK/refs), jamais en clair en base ni en log. |
| Exfiltration / abus | Audit exhaustif ; deny-by-default via grants ; apikeys révocables, clés rotables. |

## 11. Cycle de vie & résilience (§12)

- Démarrage : charger `mcp_backend` ; sessions clientes lazy (à la 1re utilisation).
- Backend injoignable : ne pas faire échouer tout `tools/list` ; exclure ce backend, journaliser, le signaler indisponible dans `gateway__list_backends`.
- Health check périodique par backend ; rouvrir la session si besoin.
- Refresh catalogue : `list_changed` (push) ou TTL de secours.
- Timeout par appel backend → erreur `timeout` mappée + audit.

## 12. Pré-requis fonctionnel manquant — curation par grant

La spec §8.2/§8.3 applique une **curation** (`expose_mode`/`expose`) au niveau du grant. **Le lot 1 ne l'a pas modélisée** (`mcp_apikey_grant` n'a pas ces colonnes — décision « hors lot 1 car suppose le catalogue »). Le catalogue arrivant ici, ce lot **ajoute** `expose_mode` (`all|allowlist|denylist`, défaut `all`) + `expose` (jsonb, défaut `[]`) à `mcp_apikey_grant` (migration 018), et câble la curation dans l'agrégation + l'UI (édition de la curation par grant). Défaut `all` → comportement inchangé pour les grants existants.

## 13. Gestion des erreurs (§13)

| Cas | Réponse au client |
|---|---|
| Tool namespacé inconnu | erreur MCP « method/tool not found » |
| Principal non autorisé | `denied` (ne révèle pas l'existence du backend) |
| Backend injoignable / timeout | erreur explicite avec `backend_id`, sans détails internes |
| Tool `quarantined` | « tool indisponible (en attente d'approbation) » |
| Erreur métier backend | erreur MCP du backend transmise telle quelle |
| Clé non résoluble au runtime (harpocrate) | erreur explicite + audit `error` |

## 14. Tests

- **Faux backend MCP in-process** monté avec le SDK `mcp` (tools/resources/prompts de démo, capable d'émettre `list_changed`) comme cible → teste client, connexions, catalogue, agrégation, serveur **sans réseau**.
- DB via testcontainers (CI Docker `test.yml`).
- Cas obligatoires : namespacing/découpe sur premier `__`, deny-by-default (grant absent → `denied`), quarantaine (hash changé → exclu + erreur), résolution KEK (round-trip), backend public (pas de bearer), backend injoignable (exclu de `tools/list`), timeout, audit écrit, curation `allowlist`/`denylist`.
- Front : édition de la curation par grant (Vitest).

## 15. Conventions

SQLAlchemy Core ; pydantic v2 `extra="forbid"` ; `from __future__ import annotations` ; fichiers ≤ 300 lignes ; logs structlog sans secret ; branche `dev` ; commits conventionnels FR ; TDD ; validation des tests sur la CI Docker (Docker absent en local).

## 16. Découpage d'implémentation suggéré (pour le plan)

1. Dépendance `mcp` + KEK système (`runtime_secrets`) + migration du chiffrement `local` du lot 1.
2. Migration 018 (`mcp_tool_catalog`, `mcp_audit_log`, colonnes curation sur `mcp_apikey_grant`) + couches DB.
3. Client MCP backend + pool de connexions (faux backend de test).
4. Catalogue + épinglage/quarantaine + refresh.
5. Agrégation (grants → curation → namespacing).
6. Serveur MCP frontal `/mcp` (auth apikey, initialize, tools/) + montage app + audit.
7. resources/ + prompts/.
8. Notifications + health/résilience.
9. Curation par grant côté UI.

## 17. Critères d'acceptation

- Un client MCP authentifié par apikey, connecté à `/mcp`, voit les tools/resources/prompts de tous ses backends autorisés, correctement préfixés, et peut en invoquer un (routé, authentifié avec la bonne clé, résultat fidèle).
- Backend public (sans clé) : fédéré sans bearer.
- Une redéfinition de primitive est mise en quarantaine et exclue jusqu'à approbation.
- Tout appel est tracé dans `mcp_audit_log`.
- Backend injoignable : `tools/list` reste fonctionnel pour les autres ; signalé dans `gateway__list_backends`.
- Tout vert sur la CI Docker (`test.yml`).
