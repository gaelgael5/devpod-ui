# SPEC — Passerelle de fédération MCP

**Composant** : `mcp-gateway` (posée à côté du portail devpod-ui)
**Statut** : Draft
**Public visé** : implémenteurs du portail et des services co-localisés (RAG, workflow, à venir)

---

## 1. Objet

La passerelle expose **un point d'entrée MCP unique** (`wrk.yoops.org`) que les clients MCP — au premier rang desquels Claude web via un connecteur custom — utilisent pour atteindre **plusieurs services MCP internes** sans connaître leur existence individuelle.

Elle résout trois problèmes :

1. Un client MCP (Claude web) ne se connecte qu'à **une seule URL**. La passerelle fédère N backends derrière cette URL.
2. Éviter le *config drift* : un service s'enregistre une fois, tous les clients en bénéficient.
3. Centraliser les préoccupations transverses : authentification, autorisation, audit, et protection contre les menaces propres à MCP.

La passerelle **agit simultanément comme serveur MCP** (face aux clients) **et comme client MCP** (face aux backends).

---

## 2. Périmètre

### Dans le périmètre
- Fédération des primitives **tools**, **resources**, **prompts** de backends MCP.
- Routage des appels par préfixe de namespace.
- Registre déclaratif des backends en base PostgreSQL.
- Curation : exposition sélective des tools par backend.
- Authentification entrante (client → passerelle) et sortante (passerelle → backend).
- Audit de chaque invocation fédérée.
- Détection des redéfinitions de tools (anti rug-pull).

### Hors périmètre (évolutions ultérieures)
- Fédération hiérarchique / imbriquée (une passerelle comme backend d'une autre).
- Surfaces de tools différenciées par consommateur (au-delà du scope par principal).
- « Code mode » (orchestration multi-tools côté passerelle).
- Sampling / Roots / Elicitation côté backend (non requis au départ).

---

## 3. Vue d'ensemble

```
Claude web ──HTTPS/MCP──> Caddy ──> mcp-gateway ──┬─MCP client─> rag.yoops.org/mcp
 (1 connecteur)                        │           ├─MCP client─> wf.yoops.org/mcp
                                       │           └─MCP client─> devpod dispatcher
                              PostgreSQL (registre,│
                              catalogue, audit)    └─> SecretResolver (gestion secrets)
```

- **Caddy** reste un proxy de transport (TLS, edge via Cloudflare Tunnel). Aucune logique de routage de tools dans Caddy.
- **mcp-gateway** porte toute la logique de fédération.
- **PostgreSQL** (base du portail) héberge le registre, le catalogue de tools mis en cache, le scope par principal et l'audit.
- **SecretResolver** : interface vers la gestion des secrets (en cours d'implémentation), résout les références `${vault://...}`.

---

## 4. Concepts

| Terme | Définition |
|---|---|
| **Backend** | Un service MCP interne fédéré (rag, workflow, devpod…). Son `id` sert de préfixe de namespace. |
| **Namespace** | Préfixe `<backend_id>` appliqué à chaque primitive fédérée pour éviter les collisions. |
| **Nom namespacé** | `<backend_id>__<nom_original>`, séparateur `__`. Ex. `rag__search`. |
| **Catalogue** | Agrégat des tools/resources/prompts exposés, mis en cache et épinglé en base. |
| **Clé de service** | Credential sortant d'un backend. Un backend en possède **1..N**. Chaque clé porte un **slug** fonctionnel (unique par service, ex. `read`/`admin`), une **description**, et une référence de secret (`auth_ref`). |
| **Profil** | Paquet nommé de **grants**. Un grant = un service + **une** clé de service + une curation de tools. Pointe **plusieurs services**. Couche de politique **mutable**. |
| **Apikey client** | Credential entrant émis à un client. Pointe **un seul profil** ; ne fige aucun droit (tout est résolu via le profil à l'appel). |
| **Contrat backend** | Ensemble minimal d'exigences qu'un service doit honorer pour être fédérable (§7). |

---

## 5. Modèle de données (PostgreSQL)

Accès via **asyncpg**, modèles **pydantic v2**. Pas d'ORM lourd.

### 5.1 `mcp_backend` (infos de connexion uniquement)
```sql
CREATE TABLE mcp_backend (
    id         text PRIMARY KEY,                   -- = préfixe namespace, ^[a-z0-9_]+$, sans "__"
    name       text NOT NULL,
    url        text NOT NULL,
    transport  text NOT NULL DEFAULT 'streamable_http'
               CHECK (transport IN ('streamable_http','sse','stdio')),
    enabled    boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
```
> Les credentials et la curation ne sont **pas** ici : un backend peut avoir plusieurs clés, et la curation dépend du profil (§5.4).

### 5.2 `mcp_backend_key` (1..N clés par service)
```sql
CREATE TABLE mcp_backend_key (
    id          text PRIMARY KEY,
    backend_id  text NOT NULL REFERENCES mcp_backend(id) ON DELETE CASCADE,
    slug        text NOT NULL,                     -- clef fonctionnelle, ex. 'read', 'admin'
    description text NOT NULL,                      -- descriptif lisible de ce que la clé autorise
    auth_ref    text NOT NULL,                      -- ${vault://...} résolu par SecretResolver
    enabled     boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (backend_id, slug)                       -- la clef fonctionnelle est unique au sein du service
);
```
> Chaque clé représente une identité/scope distincte **côté backend**, identifiée fonctionnellement par son `slug`. La rotation se fait en remplaçant l'`auth_ref` d'un slug, ou en ajoutant un slug puis en retirant l'ancien.

### 5.3 `mcp_tool_catalog` (cache + épinglage anti rug-pull)
```sql
CREATE TABLE mcp_tool_catalog (
    namespaced_name text PRIMARY KEY,              -- ex. rag__search
    backend_id      text NOT NULL REFERENCES mcp_backend(id) ON DELETE CASCADE,
    original_name   text NOT NULL,
    kind            text NOT NULL CHECK (kind IN ('tool','resource','prompt')),
    definition      jsonb NOT NULL,                -- définition telle que renvoyée par le backend
    definition_hash text NOT NULL,                 -- sha256 de definition, pour détecter un changement
    first_seen      timestamptz NOT NULL DEFAULT now(),
    last_seen       timestamptz NOT NULL DEFAULT now(),
    quarantined     boolean NOT NULL DEFAULT false -- true si redéfinition détectée et non approuvée
);
```

### 5.4 Profils, grants et apikeys clients
```sql
-- Un profil = un paquet nommé de grants (couche de politique mutable)
CREATE TABLE mcp_profile (
    id    text PRIMARY KEY,
    label text NOT NULL
);

-- Un grant : ce service, via UNE clé de service, avec cette curation de tools.
-- PK (profile_id, backend_id) => un seul grant par service dans un profil => une seule clé par service.
CREATE TABLE mcp_profile_grant (
    profile_id     text NOT NULL REFERENCES mcp_profile(id) ON DELETE CASCADE,
    backend_id     text NOT NULL REFERENCES mcp_backend(id) ON DELETE CASCADE,
    backend_key_id text NOT NULL REFERENCES mcp_backend_key(id) ON DELETE CASCADE,
    expose_mode    text NOT NULL DEFAULT 'allowlist'
                   CHECK (expose_mode IN ('all','allowlist','denylist')),
    expose         jsonb NOT NULL DEFAULT '[]'::jsonb,  -- noms de tools (originaux)
    PRIMARY KEY (profile_id, backend_id)
);

-- L'apikey client : un hash + le lien vers UN profil unique
CREATE TABLE mcp_apikey (
    id         text PRIMARY KEY,
    hash       text NOT NULL,              -- argon2/sha256 ; valeur claire montrée une seule fois
    label      text,
    profile_id text NOT NULL REFERENCES mcp_profile(id) ON DELETE RESTRICT,
    revoked    boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);
```
> **Indirection clé.** L'apikey ne porte aucun droit en propre : elle référence **un profil**. Les droits (services, clés, tools) sont **résolus à chaque appel** via ce profil et ses grants. Un profil modifié après émission de l'apikey prend effet immédiatement, sans réémission.
>
> Chaîne complète : `apikey → profil → grants → (service + clé de service + curation)`. Un profil pointe **plusieurs services** ; chaque service y est pointé par **une seule clé**.
>
> La curation (`expose_mode` / `expose`) vit **au niveau du grant** : un même service peut exposer des sous-ensembles de tools différents selon le profil.
>
> `ON DELETE RESTRICT` sur `profile_id` : on ne supprime pas un profil encore référencé par des apikeys actives.
>
> Pour l'auth OIDC Keycloak, mapper un rôle/groupe OIDC vers **un** `mcp_profile` : les deux méthodes d'auth convergent vers la même couche « profil ».

### 5.5 `mcp_audit_log`
```sql
CREATE TABLE mcp_audit_log (
    id              bigserial PRIMARY KEY,
    ts              timestamptz NOT NULL DEFAULT now(),
    apikey_id       text,                  -- ou sub OIDC
    profile_id      text,                  -- profil ayant accordé l'accès
    namespaced_name text,
    backend_id      text,
    backend_key_id  text,                  -- clé de service utilisée
    latency_ms      integer,
    status          text NOT NULL,         -- ok | error | denied | timeout
    error           text
);
```

> Affinité de session : non modélisée tant que chaque backend est mono-instance (cas actuel, co-localisé). Si un backend passe multi-instance, ajouter `mcp_session_affinity(client_session_id, backend_id, backend_session_id)`.

---

## 6. Résolution des secrets

La gestion des secrets étant **en cours d'implémentation**, la passerelle n'en dépend que via une interface, jamais d'une implémentation concrète :

```python
class SecretResolver(Protocol):
    async def resolve(self, ref: str) -> str:
        """Résout une référence type ${vault://chemin} ou ${env://NOM} en valeur claire."""
```

Règles :
- La passerelle ne **persiste jamais** de secret en clair ; `mcp_backend_key.auth_ref` ne stocke qu'une **référence**.
- La résolution a lieu à l'établissement (ou au rafraîchissement) de la session MCP vers le backend, **pour la clé désignée par le grant** en cours.
- Tant que le gestionnaire cible n'est pas livré, une implémentation `EnvSecretResolver` (résout `${env://...}`) suffit comme palier ; le contrat ne change pas ensuite.

---

## 7. Contrat backend (exigences de fédérabilité)

Tout service co-localisé qui veut être fédéré **DOIT** :

1. Parler **MCP sur Streamable HTTP** à une URL stable.
2. Implémenter `initialize` (négociation de capacités) ; **DEVRAIT** fournir un champ `instructions`.
3. Implémenter `tools/list` avec des **noms de tools stables** et **sans `__`** (séparateur réservé).
4. Émettre `notifications/tools/list_changed` (et variantes resources/prompts) quand son catalogue change, pour permettre la ré-agrégation.
5. Accepter un **bearer token** (fourni par la passerelle, résolu via `SecretResolver`) comme authentification.
6. Retourner des erreurs conformes au **modèle d'erreur MCP** (JSON-RPC).
7. **DEVRAIT** exposer des `outputSchema` pour des résultats structurés.

Un backend qui ne respecte pas (3) — noms contenant `__` — voit ses tools **rejetés** au chargement, avec entrée d'audit.

---

## 8. Comportement de la passerelle (face client)

### 8.1 `initialize`
- Annonce ses propres `serverInfo` et capacités (`tools`, `resources`, `prompts`, `notifications.*_list_changed`).
- Compose un champ `instructions` expliquant la **convention de namespacing** et listant les backends accessibles via les profils de l'appelant.
- Expose un tool natif `gateway__list_backends` (découverte des backends accessibles à l'appelant).

### 8.2 `tools/list`
Algorithme :
1. Résoudre l'appelant → apikey (ou sub OIDC) → **le profil** → **grants** (`mcp_profile_grant`).
2. Pour chaque grant dont le backend est `enabled` : lire le catalogue (cache `mcp_tool_catalog`, rafraîchi sur `list_changed` ou TTL).
3. Appliquer la **curation du grant** : `expose_mode` + `expose`.
4. Appliquer le **namespacing** : `original_name → <backend_id>__<original_name>`.
5. Exclure les entrées `quarantined = true`.
6. Concaténer avec les tools natifs de la passerelle (`gateway__*`) et retourner.

### 8.3 `tools/call`
Algorithme :
1. Découper le nom namespacé sur le **premier `__`** → `(backend_id, original_name)`.
2. Résoudre l'appelant → son profil → **le grant** couvrant `backend_id` ET autorisant `original_name` (curation). Aucun grant correspondant → erreur `denied`.
3. Vérifier que `(namespaced_name)` n'est pas `quarantined`.
4. Lire la **clé de service** du grant (`backend_key_id`), résoudre son secret (`SecretResolver`), garantir une session MCP cliente authentifiée avec cette clé.
5. Forwarder `tools/call` avec `original_name` et les arguments.
6. Mapper le résultat / l'erreur MCP du backend vers le client.
7. Journaliser dans `mcp_audit_log` (apikey/sub, profil, backend, clé, tool, latence, statut).

> Sélection de clé déterministe par construction : un profil n'a qu'un grant par service (PK `profile_id, backend_id`), donc une seule clé possible. Aucune ambiguïté à arbitrer.

### 8.4 Resources & prompts
Même schéma que tools : agrégation, namespacing des URIs/identifiants, routage par préfixe. Resources via `resources/list` + `resources/read` ; prompts via `prompts/list` + `prompts/get`.

### 8.5 Propagation des notifications
- À réception d'un `notifications/tools/list_changed` d'un backend : ré-agréger ce backend, mettre à jour `mcp_tool_catalog`, puis émettre un `notifications/tools/list_changed` **vers les clients** concernés.
- Idem resources/prompts.

---

## 9. Namespacing — convention

- **Format** : `<backend_id>__<nom_original>`.
- **Séparateur** : `__` (double underscore), réservé.
- **`backend_id`** : `^[a-z0-9_]+$`, **sans** `__`.
- **Routage** : découpe sur le **premier** `__` (le nom original peut contenir `_` simples).
- **Collision** : impossible par construction si chaque `backend_id` est unique (clé primaire).

---

## 10. Authentification & autorisation

Deux couches distinctes, qui convergent toutes deux vers la couche **profils**.

### 10.1 Entrant (client → passerelle)
- **Apikey client** : la passerelle hache la clé présentée et la retrouve dans `mcp_apikey` (non révoquée). L'apikey → **son unique profil** (`mcp_apikey.profile_id`).
- **OIDC Keycloak** (pérenne) : la passerelle valide le token, en extrait le `sub`, et mappe un rôle/groupe OIDC → **un** `mcp_profile`. S'appuie sur l'**OpenID Connect Discovery** supporté par la spec MCP récente.
- Dans les deux cas, l'autorisation effective est l'ensemble des **grants du profil** résolu.

### 10.2 Résolution dynamique (le point central)
- L'apikey ne porte **aucun droit figé** : elle ne référence qu'un profil.
- Les droits sont **résolus à chaque appel** (`tools/list` et `tools/call`) depuis Postgres. Un profil modifié, un grant ajouté/retiré, une clé de service changée → **effet immédiat** sur toutes les apikeys concernées, sans réémission.
- Cache autorisé mais **avec invalidation** sur modification de profil/grant (ou TTL court), jamais de scope gelé dans un jeton de session long.

### 10.3 Sortant (passerelle → backend)
- Le **grant** désigne la `mcp_backend_key` à utiliser. La passerelle résout son `auth_ref` et présente le **bearer token** correspondant au backend.
- Les backends **font confiance à la passerelle**, pas au client final. La passerelle est le seul point où vivent les credentials sortants.

---

## 11. Sécurité (menaces propres à MCP)

| Menace | Mitigation |
|---|---|
| **Rug pull** (redéfinition d'un tool après approbation) | Épinglage : `definition_hash` en base. Au rafraîchissement, si le hash change, marquer `quarantined = true` jusqu'à approbation manuelle. Entrée d'audit. |
| **Tool poisoning** (injection via descriptions) | Les descriptions des backends sont des données non fiables. Ne pas les exécuter ; les exposer telles quelles au client mais journaliser tout changement. |
| **Cross-server shadowing** (un backend en usurpe un autre) | Namespacing strict par `backend_id` (clé primaire) ; un backend ne peut pas publier sous le préfixe d'un autre. |
| **Fuite de credentials** | Secrets résolus à la volée, jamais persistés en clair ; `auth_ref` (sur la clé de service) = référence uniquement. |
| **Exfiltration / abus** | Audit exhaustif (`mcp_audit_log`) ; autorisation deny-by-default via profils/grants ; apikeys révocables et clés de service rotables indépendamment. |

---

## 12. Cycle de vie & résilience

- **Démarrage** : charger `mcp_backend` ; pour chaque backend `enabled`, ouvrir une session MCP cliente (lazy possible : à la première utilisation).
- **Backend injoignable** : ne pas faire échouer tout `tools/list` ; exclure ce backend, journaliser, et signaler son indisponibilité dans `gateway__list_backends`.
- **Health check** périodique par backend ; rouvrir la session si nécessaire.
- **Rafraîchissement du catalogue** : sur `list_changed` (push) ou TTL de secours.
- **Timeout** par appel backend ; au-delà → erreur `timeout` mappée au client + audit.

---

## 13. Gestion des erreurs (mapping MCP)

| Cas | Réponse au client |
|---|---|
| Tool namespacé inconnu | Erreur MCP « method/tool not found ». |
| Principal non autorisé sur le backend | Erreur `denied` (ne pas révéler l'existence du backend). |
| Backend injoignable / timeout | Erreur explicite avec `backend_id`, sans détails internes. |
| Tool `quarantined` | Erreur « tool indisponible (en attente d'approbation) ». |
| Erreur métier du backend | Erreur MCP du backend transmise telle quelle. |

---

## 14. Conventions techniques

- **Stack** : FastAPI, asyncpg, pydantic v2.
- **Persistance** : PostgreSQL (base du portail). Pas d'ORM lourd ; requêtes asyncpg.
- **Secrets** : interface `SecretResolver`, formalisme `${vault://...}` / `${env://...}`.
- **Taille des fichiers** : aucun fichier > 300 lignes.
- **Branche** : `dev` exclusivement. Commits conventionnels en français.
- **Cycle architecte** : Cadrer → Comprendre → Planifier → Agir ; capitalisation dans `LESSONS.md`.

---

## 15. Découpage d'implémentation suggéré

1. **Registre** : tables §5 + CRUD `mcp_backend` / `mcp_backend_key` + `SecretResolver` (palier `EnvSecretResolver`).
2. **Client MCP backend** : établissement de session Streamable HTTP, `initialize`, `tools/list`, `tools/call`, abonnement `list_changed`.
3. **Agrégation** : namespacing, curation par grant, cache `mcp_tool_catalog` + épinglage.
4. **Serveur MCP frontal** : `initialize` (instructions composées), `tools/list`, `tools/call`, propagation notifications, tool natif `gateway__list_backends`.
5. **Profils & apikeys** : CRUD `mcp_profile` / `mcp_profile_grant`, émission d'apikeys (hash + affectation de profils), résolution dynamique à l'appel, audit.
6. **Auth entrante** : apikey (hash), puis OIDC Keycloak (rôles → profils).
7. **Sécurité** : quarantaine anti rug-pull, deny-by-default, health checks/résilience.

---

## 16. Critères d'acceptation

- Un nouveau service devient fédérable par **une seule ligne de registre** + une ou plusieurs clés de service, sans modifier le code de la passerelle.
- Chaque clé enregistrée porte un **slug fonctionnel** (unique par service) et une **description**.
- Une **apikey client** donne accès à **un seul profil** ; un profil pointe plusieurs services, chacun via une seule clé. Modifier le profil après émission change l'accès **sans réémettre** l'apikey.
- Claude web, connecté à une **seule URL**, voit les tools de tous les backends autorisés par ses profils, correctement préfixés.
- Un `tools/call` est routé au bon backend, **avec la bonne clé de service**, et son résultat remonte sans transformation de sens.
- Une redéfinition de tool est détectée et mise en quarantaine.
- Tout appel est tracé dans `mcp_audit_log` avec apikey/sub, profil, backend, clé, latence et statut.
