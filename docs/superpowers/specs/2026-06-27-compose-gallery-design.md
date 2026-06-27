# Cadrage — Galerie Docker Compose (spec 26)

> **Statut** : design de cadrage validé avec l'architecte le 2026-06-27.
> **Base** : `specs/26-compose-gallery.md` (contrat fonctionnel). Ce document **complète** la spec 26 :
> il corrige deux écarts spec↔code découverts à l'exploration, fige les décisions de cadrage,
> et décrit le découpage en composants. En cas de conflit, **ce document fait foi** sur les points
> qu'il traite ; la spec 26 reste la référence pour le périmètre fonctionnel, le modèle de données
> de base, la surface API et les critères d'acceptation.

---

## 1. Objectif (rappel)

Galerie de templates `docker-compose` paramétrables, instanciables sur un nœud enrôlé. Cycle de vie
géré depuis l'UI (statut, logs, start/stop/restart/down). Concept **distinct des recipes**
(cf. spec 26 §1). Décisions d'archi de la spec 26 §2 conservées (interpolation native `${VAR}` + `.env`,
profiles/multi-fichiers, secrets Harpocrate en référence, pas de `:latest`).

---

## 2. Corrections à la spec 26 (écarts spec ↔ code réel)

### Correction C1 — Persistance : SQLAlchemy core + Alembic (PAS asyncpg pur)
La spec 26 §2.5 et §11 affirment « asyncpg direct, **pas** SQLAlchemy/Alembic ». **C'est faux pour ce
projet.** L'état réel du code :
- Engine : `backend/src/portal/db/engine.py` — `create_async_engine("postgresql+asyncpg://…")`,
  `get_conn()` fournit une `AsyncConnection` dans une transaction (`_get_engine().begin()`).
- Tables : déclarées en **SQLAlchemy Core** dans `backend/src/portal/db/tables.py`.
- Migrations : **Alembic** sous `backend/alembic/versions/` (dernière = `029`, **prochaine = `030`**).
- Requêtes : `conn.execute(select/insert/update/delete(...))`, `.mappings().all()`, `.scalar_one()`.

**Décision** : on suit le mécanisme du projet (ce que demande d'ailleurs la spec 26 §11 :
« réutiliser celui déjà présent, ne pas en introduire un nouveau »). Donc :
- nouvelle migration **Alembic `030`** créant `compose_template`, `compose_deployment`,
  `compose_deployment_log` ;
- tables déclarées dans `tables.py` (Core) ;
- couche DB en SQLAlchemy Core async (pas d'asyncpg en direct, pas d'ORM).

> Le DDL indicatif de la spec 26 §4 reste valide **sémantiquement** (colonnes, types, index GIN sur
> `host_ports` et `tags`) mais est exprimé via Alembic/Core, pas en `CREATE TABLE` asyncpg.

### Correction C2 — Canal d'exécution sur un nœud : à construire
La spec 26 §2.4/§5 suppose « écrire `~/devpod-compose/<id>/…` sur le nœud + `docker compose up -d`
via le canal nœud existant ». **Ce canal n'existe pas.** L'existant :
- `ws_exec` / `run_ssh_capture` (`devpod/exec.py`, `devpod/ssh_exec.py`) = **scoped workspace**
  (`devpod ssh --stdio <ws_id>`), pas nœud.
- `routes/ssh_proxy.py` = terminal SSH **interactif** (websocket) vers un host `ssh` — pas
  d'exécution non-interactive batch ni d'écriture de fichier.
- Un host `docker-tls` n'a **pas de shell** : seulement un daemon Docker en TLS ; `docker compose`
  est une **CLI** (non couverte par `aiodocker`).

**Décision** (cf. §4 décisions) : construire un **canal nœud SSH non-interactif** ; v1 limitée aux
hosts `type=ssh`.

---

## 3. Architecture & composants

### 3.1 Canal nœud (nouveau) — `backend/src/portal/devpod/host_exec.py`
Seul point d'exécution des commandes compose. Sur le modèle de `ssh_exec.run_ssh_capture` et de
`routes/ssh_proxy.py` (clé SSH du host = `host.host_cert_slug` matérialisée depuis Harpocrate,
cible = `host.address`).

- `async def run_host_command(host: HostConfig, command: str, *, timeout: float = 120.0) -> tuple[int, str, str]`
  — exécute une commande non-interactive sur le host via `ssh` (BatchMode, StrictHostKeyChecking
  géré comme `ssh_proxy`), retourne `(returncode, stdout, stderr)`.
- `async def write_host_file(host: HostConfig, remote_path: str, content: str) -> None`
  — écrit un fichier sur le host (via `cat > … <<'EOF'` ou stdin redirigé ; chemin validé, pas de
  concaténation non échappée). Crée les répertoires parents.
- Garde : refuse tout host dont `type != "ssh"` (`DevpodToolError`/erreur explicite) — v1 ssh-only.

> Réutilise la matérialisation de cert système déjà utilisée par `ssh_proxy.py`
> (`_materialize_system_cert(host.host_cert_slug)`), à factoriser si pertinent.

### 3.2 Module compose (nouveau) — `backend/src/portal/compose/`
Découpage SRP (fichiers ≤ 300 lignes) :
- `models.py` — pydantic v2 `extra="forbid"` : `ComposeTemplate`, `ComposeParam`, `ComposeDeployment`
  (+ enums source/type/status). Conforme spec 26 §4, **plus** `owner_login` (cf. C3 ci-dessous).
- `validation.py` — YAML compose parsable ; cohérence `parameters` ↔ `${VAR}` référencés dans
  `compose_content` ; lint `:latest` (warning bloquant) ; tout port hôte exposé doit être un
  paramètre `type=port` (spec 26 §7).
- `db.py` — couche SQLAlchemy Core (CRUD templates + deployments ; requête de conflit de ports).
- `env_builder.py` — génère le contenu `.env` depuis `env_values` (résolution secrets injectée).
- `service.py` — orchestration lifecycle : résout secrets en mémoire, `write_host_file` du
  `docker-compose.yml` + `.env` sous `~/devpod-compose/<deployment_id>/`, lance les commandes
  `docker compose -p <id> …` via `run_host_command`, parse `ps --format json` → `status`,
  persiste les logs d'opération (blob).
- `ports.py` — détection de conflit (cf. 3.5).

### 3.3 Routes — `backend/src/portal/routes/compose.py`
Préfixe `/api/compose` (spec 26 §5). RBAC (cf. C3) :
- **Templates** (`GET/POST/PUT/DELETE /templates[...]`) → `require_admin`.
- **Deployments** (`GET/POST /deployments`, `POST /deployments/{id}/{stop,start,restart}`,
  `DELETE /deployments/{id}`, `GET /deployments/{id}/logs`, `GET /deployments/{id}/status`)
  → `require_user`, scopés par `owner_login` (un dev ne voit/pilote que ses déploiements ;
  un admin voit tout).

### 3.4 Logs — live + blobs d'opération
- **Services** : `GET /deployments/{id}/logs?service=&tail=` → exécute
  `docker compose -p <id> logs --no-color --tail=<n> [service]` **live** via `run_host_command`,
  retourne le texte. Rien de stocké (c'est l'état courant).
- **Opérations** (`up`/`down`/`restart`/`stop`/`start`) : la sortie combinée est **persistée en blob**
  scopé `deployment_id`, pour le post-mortem (notamment `status=error` quand le `up` échoue et
  qu'aucun conteneur n'existe).
- **Implémentation du stockage** : `log_blobs` actuel est scopé `ws_id`
  (`tables.workspace_log_blobs`). On **ne le détourne pas**. Nouvelle table
  `compose_deployment_log` (même forme : `id`, `deployment_id`, `operation`, `content`,
  `started_at`, `finished_at`) + petite couche `compose/db.py` miroir de `db/log_blobs.py`.

### 3.5 Ports — détection de conflit
- Tout port hôte exposé = paramètre `type=port` (jamais codé en dur — vérifié au lint, spec 26 §7).
- `compose_deployment.host_ports int[]` (colonne dédiée, index GIN).
- **Détection autoritative (SQL, node-wide, tous owners)** :
  `SELECT … FROM compose_deployment WHERE node_id = $1 AND host_ports && $2::int[]`.
- **Enrichissements** : inclure aussi les `workspace_status.host_port` du même host (port-forwards
  workspace) dans l'ensemble occupé ; **check live best-effort** avant `up`
  (`ss -ltn` ou `docker ps --format '{{.Ports}}'` via `run_host_command`) pour les ports pris par
  des process hors-compose.
- Conflit → **409** explicite + **port libre suggéré** (scan) pour pré-remplir le formulaire UI.

### 3.6 Secrets (Harpocrate) — réutilisation
- `secrets/resolver.py::resolve(value, scope, backend)` parse déjà `${vault://…}` / `${env://…}`.
- `Scope(kind="user", secret_ns=<celui du dev déployeur>, login=<dev>)`.
- Résolution **strictement en mémoire** au `POST /deployments` (spec 26 §6). Le `.env` écrit sur le
  nœud contient la valeur résolue. **Invariante non négociable** : la base ne stocke QUE des
  références `${vault://…}` dans `env_values` ; aucune valeur résolue n'est jamais persistée.
- Durcissement du `.env` sur le nœud : **hors v1** (spec 26 §3/§6, décidé).

### 3.7 Frontend — `frontend/src/features/compose/`
React 19 + Vite + TS strict + TanStack Query + Zustand + shadcn/ui (patterns existants, cf.
`features/profiles`, `features/mcp`). Vues spec 26 §8 :
- **Galerie** (templates) — admin : grille de cartes, filtre par tag, créer/importer.
- **Éditeur de template** — admin : compose brut (coloration YAML) + éditeur de `parameters` ;
  validation à la volée (parsable, params↔`${VAR}`, alerte `:latest`).
- **Dialogue d'instanciation** — dev : sélection nœud (`type=ssh`) + formulaire auto-généré depuis
  `parameters` (widget selon `type` ; `secret` → champ de référence ; `port` → conflit live) ;
  aperçu `.env` (secrets masqués).
- **Vue Déploiements** — dev : liste de SES stacks (nom, nœud, statut, ports) + start/stop/restart/down
  + panneau de logs.
- État serveur via TanStack Query ; UI locale via Zustand.

---

## 4. Décisions de cadrage actées (2026-06-27)

| # | Sujet | Décision |
|---|-------|----------|
| D1 | Canal nœud | SSH non-interactif **host-scoped** (`host_exec.py`) ; **hosts `type=ssh` uniquement** en v1 ; `docker-tls` → backlog. |
| D2 | Hosts éligibles | **Tout host `type=ssh`** (usage `workspaces` **et** `tests`). |
| D3 | RBAC | Templates CRUD = **admin** ; deployments = **dev** (`require_user`) + **`owner_login`** ; admin voit tout. |
| D4 | Logs | Services **live** via SSH ; opérations (up/down/restart/stop/start) **persistées en blob** (`compose_deployment_log`), scope `deployment_id`. |
| D5 | Ports | Conflit **SQL node-wide** sur `host_ports` (+ `workspace_status.host_port` du host) + **check live best-effort** ; 409 + port suggéré. |
| D6 | Persistance | **SQLAlchemy Core + Alembic 030** (correction de la spec §2.5/§11). |
| D7 | Secrets | Réutilise `resolver.resolve` + `Scope(user, secret_ns dev)` ; résolution en mémoire ; DB = refs uniquement. |

### Delta modèle de données vs spec 26 §4
- `compose_deployment` : **+ `owner_login text NOT NULL`** (+ index `(node_id)` déjà prévu ;
  ownership filtré côté requêtes/routes).
- Nouvelle table **`compose_deployment_log`** (`id`, `deployment_id` FK, `operation`, `content`,
  `started_at`, `finished_at`).
- `compose_template` / `compose_deployment` : colonnes & index conformes spec 26 §4 (GIN `tags`,
  GIN `host_ports`, FK `template_id`).

---

## 5. Hors périmètre v1 (confirmé)
Spec 26 §3 + cadrage : hosts `docker-tls` ; orchestration multi-nœuds d'une stack ; build d'images ;
durcissement persistance `.env` sur le nœud ; versionnement de l'historique des `env_values` ;
édition visuelle du graphe de services.

---

## 6. Réutilisé tel quel (vérifié à l'exploration)
Alembic (→030) · SQLAlchemy Core async (`db/engine.py`, `db/tables.py`) · `secrets/resolver.py` ·
`auth` (`require_user`/`require_admin`, `get_conn`) · matérialisation cert SSH host
(`ssh_proxy.py`) · patterns frontend (`shared/api/client.ts`, TanStack Query, Zustand, shadcn/ui).

---

## 7. Points à confirmer à l'implémentation
1. Factorisation de `_materialize_system_cert` (aujourd'hui dans `ssh_proxy.py`) si `host_exec.py`
   en a besoin — extraire dans un util partagé plutôt que dupliquer.
2. Forme exacte de l'écriture de fichier distant (`cat <<'EOF'` vs `sftp`/`scp`) — choisir la plus
   robuste/échappée dans `write_host_file`.
3. Stratégie de rafraîchissement du `status` live dans `GET /deployments` (parse `ps` à la volée
   pour chacun vs colonne `status` mise à jour à chaque opération + rafraîchissement à la demande).

---

## 8. Critères d'acceptation
Ceux de la spec 26 §10 (1→6), avec ces précisions de cadrage :
- (3) le `up` passe par le **canal SSH host-scoped** (`run_host_command`/`write_host_file`), host `ssh`.
- (4) conflit de port détecté **node-wide** (tous owners) + suggestion.
- (5) secret en `${vault://…}` en base, résolu en mémoire, jamais en clair.
- (+) un déploiement créé par un dev n'est visible/pilotable que par lui (et les admins) — ownership.
