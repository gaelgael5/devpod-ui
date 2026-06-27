# SPEC — Galerie Docker Compose (devpod-ui)

> Fonctionnalité : permettre à l'utilisateur de créer/importer des stacks `docker-compose`
> paramétrées depuis une galerie, puis de les lancer sur une machine de test (nœud enrôlé).
> Repo : `gaelgael5/devpod-ui` — branche `dev` uniquement — commits conventionnels en français.

---

## 1. Contexte & objectif

devpod-ui orchestre des workspaces DevPod qui exécutent des agents Claude Code. Certains
agents ont besoin de **services à côté** du workspace (ex. un navigateur headless Browserless,
un SearXNG, une base…). Aujourd'hui il n'existe aucun moyen propre de déployer une stack
multi-conteneurs sur une machine de test.

On ajoute une **galerie de templates `docker-compose`** : l'utilisateur importe ou crée un
template paramétrable, renseigne les valeurs via un formulaire, puis lance une ou plusieurs
stacks sur un nœud cible. Le cycle de vie (statut, logs, stop/restart, teardown) est géré
depuis l'UI.

**Ce concept est distinct des `recipes` (Dev Container Features) et ne doit PAS être fusionné
avec elles.** Les recipes provisionnent l'*intérieur* d'un workspace (script bash, au build,
mono-conteneur). La galerie compose déclare une *topologie de services* (YAML, au runtime,
multi-conteneurs). Deux modèles mentaux, deux vues UI séparées.

---

## 2. Décisions d'architecture déjà tranchées (ne pas re-débattre)

1. **Pas de moteur de templating maison.** On s'appuie sur l'interpolation **native** de
   compose (`${VAR}`) + un fichier `.env`. L'UI génère le `.env`, compose fait la substitution.
   Interdiction d'introduire un dialecte `{{ ma_variable }}` par-dessus le compose.
2. **Variation structurelle = mécanismes natifs.** Si un service doit être activable/désactivable,
   utiliser `profiles:` et/ou la composition multi-fichiers (`-f base.yml -f override.yml`).
   Pas de génération de YAML à la main.
3. **Secrets via Harpocrate.** Les paramètres de type `secret` ne sont JAMAIS stockés en clair
   en base. On stocke une référence `${vault://...}`, résolue **au lancement** (just-in-time)
   via Harpocrate, strictement en mémoire. Voir §6.
4. **Transport vers le nœud = canal existant.** Réutiliser le mécanisme d'enrôlement multi-nœuds
   (SSH / mTLS, CA détenue par le portail). Ne pas créer un nouveau canal d'exécution.
5. **Stockage = PostgreSQL via asyncpg.** Les models sont persistés en tables (cf. §4).
   Pas de SQLAlchemy/Alembic ; SQL direct via asyncpg, selon le mécanisme de migration
   **déjà en place dans le projet** (à confirmer / réutiliser — ne pas en introduire un nouveau).
6. **Pas de `:latest` dans les templates.** Les images doivent être épinglées sur des tags datés.
   Un lint le vérifie à l'import/création (warning bloquant configurable).

---

## 3. Périmètre

### Inclus
- CRUD de **templates compose** (galerie) : créer (coller un compose + définir les paramètres),
  importer, lister, éditer, supprimer.
- **Instanciation** d'un template sur un nœud cible → génération du `.env` + lancement
  `docker compose up -d`.
- **Cycle de vie** d'un déploiement : statut/santé, logs, start/stop/restart, down (teardown).
- **Gestion des ports hôte** : détection de conflit sur le nœud, suggestion de port libre.
- Lancement de **plusieurs déploiements** sur la même machine de test.

### Hors périmètre (cette itération)
- Build d'images custom (on consomme des images publiées).
- Orchestration multi-nœuds d'une même stack (un déploiement = un nœud).
- Auto-scaling / health-checks avancés au-delà de `docker compose ps`.
- Édition visuelle du graphe de services (l'utilisateur édite du YAML compose brut).
- **Audit / versionnement de l'historique des `env_values`** d'un déploiement (décidé : non).
- **Durcissement de la persistance du `.env` sur le nœud** (décidé : rien pour le moment — voir §6).

---

## 4. Modèle de données (pydantic v2 `extra="forbid"` + tables PostgreSQL)

### `ComposeTemplate` (item de galerie)
| champ | type pydantic | colonne SQL | notes |
|---|---|---|---|
| `id` | `str` (slug) | `text PRIMARY KEY` | identifiant stable |
| `name` | `str` | `text` | nom affiché |
| `description` | `str` | `text` | |
| `tags` | `list[str]` | `text[]` | catégorisation galerie |
| `version` | `str` | `text` | version du template (semver libre) |
| `compose_content` | `str` | `text` | le `docker-compose.yml` **verbatim**, placeholders natifs `${VAR}` |
| `parameters` | `list[ComposeParam]` | `jsonb` | définition des variables exposées |
| `source` | `enum(user, builtin, imported)` | `text` | origine |
| `created_at` / `updated_at` | `datetime` | `timestamptz` | |

### `ComposeParam` (élément du JSONB `parameters`)
| champ | type | notes |
|---|---|---|
| `key` | `str` | nom de la variable d'env (ex. `BROWSERLESS_PORT`) |
| `label` | `str` | libellé formulaire |
| `description` | `str \| None` | |
| `type` | `enum(string, number, bool, enum, port, secret)` | pilote widget + validation |
| `default` | `str \| None` | |
| `required` | `bool` | |
| `options` | `list[str] \| None` | pour `type=enum` |
| `secret_ref_hint` | `str \| None` | pour `type=secret` : préfixe/chemin Harpocrate suggéré |

### `ComposeDeployment` (instance lancée)
| champ | type pydantic | colonne SQL | notes |
|---|---|---|---|
| `id` | `str` (slug) | `text PRIMARY KEY` | sert de `-p` (project name) compose |
| `template_id` | `str` | `text REFERENCES compose_template(id)` | |
| `template_version` | `str` | `text` | version figée au lancement |
| `node_id` | `str` | `text` | nœud cible (enrôlé) |
| `env_values` | `dict[str, str]` | `jsonb` | valeurs renseignées ; **secrets en `${vault://...}`**, jamais en clair |
| `host_ports` | `list[int]` | `int[]` | **colonne dédiée** (pas dans le JSONB) pour la détection de conflit SQL |
| `status` | `enum(created, running, partial, stopped, error)` | `text` | dérivé de `docker compose ps` |
| `last_error` | `str \| None` | `text` | |
| `created_at` / `updated_at` | `datetime` | `timestamptz` | |

### Schéma (DDL indicatif)
```sql
CREATE TABLE compose_template (
  id              text PRIMARY KEY,
  name            text NOT NULL,
  description     text NOT NULL DEFAULT '',
  tags            text[] NOT NULL DEFAULT '{}',
  version         text NOT NULL,
  compose_content text NOT NULL,
  parameters      jsonb NOT NULL DEFAULT '[]',
  source          text NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE compose_deployment (
  id               text PRIMARY KEY,
  template_id      text NOT NULL REFERENCES compose_template(id),
  template_version text NOT NULL,
  node_id          text NOT NULL,
  env_values       jsonb NOT NULL DEFAULT '{}',  -- secrets = refs ${vault://...} uniquement
  host_ports       int[] NOT NULL DEFAULT '{}',
  status           text NOT NULL DEFAULT 'created',
  last_error       text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_deployment_node   ON compose_deployment (node_id);
CREATE INDEX idx_deployment_ports  ON compose_deployment USING gin (host_ports);
CREATE INDEX idx_template_tags     ON compose_template   USING gin (tags);
```

> Détection de conflit de port (§7) = requête native sur la colonne `int[]` :
> `... WHERE node_id = $1 AND host_ports && $2::int[]` (opérateur d'intersection `&&`).
>
> **Invariante secrets** : aucune colonne ne contient jamais une valeur de secret résolue.
> `env_values` ne stocke que des références `${vault://...}`. La résolution Harpocrate est
> strictement en mémoire au moment du `up` (§6).

---

## 5. API backend (FastAPI)

Préfixe : `/api/compose`. Auth Keycloak OIDC (comme le reste du portail). Logs JSON structurés.

### Templates
- `GET    /templates` — liste (filtrable par `tag`).
- `GET    /templates/{id}` — détail.
- `POST   /templates` — créer (body = compose brut + paramètres). Valide : YAML compose parsable,
  cohérence params ↔ `${VAR}` référencés, lint `:latest`.
- `PUT    /templates/{id}` — éditer.
- `DELETE /templates/{id}` — supprimer.

### Déploiements
- `GET    /deployments` — liste, avec statut live (rafraîchi via `docker compose ps` sur le nœud).
- `POST   /deployments` — instancier : `{ template_id, node_id, name, env_values }`.
  Étapes serveur :
  1. Charger le template, valider que tous les params `required` sont fournis.
  2. Pour les params `type=port` : vérifier la disponibilité sur le nœud (§7) → 409 si conflit.
  3. Résoudre les params `type=secret` via Harpocrate (§6) — **en mémoire uniquement**.
  4. Écrire sur le nœud `~/devpod-compose/<deployment_id>/{docker-compose.yml, .env}` via le canal nœud.
  5. `docker compose --env-file .env -p <deployment_id> up -d`.
  6. Persister la ligne `compose_deployment` (secrets = refs vault, pas les valeurs).
- `POST   /deployments/{id}/stop` — `docker compose -p <id> stop`.
- `POST   /deployments/{id}/start` — `docker compose -p <id> start`.
- `POST   /deployments/{id}/restart` — `restart`.
- `DELETE /deployments/{id}` — `docker compose -p <id> down -v` (option `-v` confirmée côté UI)
  + suppression du dossier distant + de la ligne en base.
- `GET    /deployments/{id}/logs?service=&tail=` — **réutiliser le mécanisme de logs existant
  du portail** ; ne pas introduire un nouveau transport.
- `GET    /deployments/{id}/status` — parse `docker compose -p <id> ps --format json`.

Toutes les commandes `docker compose` passent par le **canal nœud existant** (SSH/mTLS),
jamais par un shell local au portail.

---

## 6. Gestion des secrets (Harpocrate)

- Dans `env_values`, un paramètre `type=secret` est stocké **sous forme de référence** :
  `MON_TOKEN=${vault://chemin/du/secret}`. Jamais la valeur.
- Au lancement (`POST /deployments`, étape 3), le backend résout ces références via Harpocrate
  et produit la valeur réelle **en mémoire**.
- Le `.env` écrit sur le nœud contient la valeur résolue. **Décision actuelle : on ne durcit pas
  la persistance du `.env` sur le nœud pour le moment** (pas de suppression post-`up`, pas de
  tmpfs). Limitation connue et acceptée, à revisiter ultérieurement.
- **Invariante non négociable** : la base de données ne contient QUE des références
  `${vault://...}` ; aucune valeur de secret résolue n'y est jamais écrite.

---

## 7. Gestion des ports hôte (point critique multi-stacks)

Plusieurs stacks sur la même machine de test → risque de collision (Browserless 3000,
SearXNG 8080, etc.). Règles :
- Tout port hôte exposé doit être un paramètre `type=port` (jamais codé en dur dans le compose).
- À l'instanciation, détection de conflit via requête SQL sur `compose_deployment.host_ports`
  (`node_id = $1 AND host_ports && $2`), complétée si besoin par un `docker ps` sur le nœud.
- En cas de conflit : 409 explicite + suggestion d'un port libre dans la réponse, pour
  pré-remplir le formulaire UI.

---

## 8. Frontend (React 19 / Vite / TS strict / TanStack Query / Zustand / shadcn/ui)

- **Vue Galerie** : grille de cartes de templates (nom, tags, description, version). Filtre par tag.
  Bouton « Créer un template » + « Importer ».
- **Éditeur de template** : édition du compose brut (coloration YAML) + éditeur de la liste de
  paramètres (key, type, label, défaut, requis…). Validation à la volée (compose parsable,
  params ↔ `${VAR}`, alerte `:latest`).
- **Dialogue d'instanciation** : sélection du nœud cible + formulaire auto-généré à partir des
  `parameters` (widget selon `type` ; `secret` → sélecteur/champ de référence Harpocrate ;
  `port` → champ avec détection de conflit). Aperçu du `.env` résultant (secrets masqués).
- **Vue Déploiements** : liste des stacks lancées (nom, nœud, statut, ports) + actions
  start/stop/restart/down + panneau de logs (réutilisant le mécanisme de logs existant du portail).
- État serveur via TanStack Query ; état UI local via Zustand.

---

## 9. Contraintes & conventions
- Fichiers source ≤ 300 lignes ; découper si nécessaire.
- pydantic v2 `extra="forbid"` partout. asyncpg en direct, pas de SQLAlchemy/Alembic.
- TypeScript strict ; pas de `any`.
- Logs JSON structurés côté backend.
- Commits conventionnels en français, sur `dev` uniquement.

---

## 10. Critères d'acceptation
1. Je peux créer un template compose (ex. Browserless) en collant un `docker-compose.yml` avec
   `${BROWSERLESS_PORT}` et déclarer le paramètre `port` associé.
2. À l'import, un compose contenant `image: …:latest` déclenche une alerte de lint.
3. Je peux instancier ce template sur un nœud de test ; un `.env` est généré et
   `docker compose up -d` est exécuté **via le canal nœud existant**.
4. Un second déploiement réclamant le même port hôte renvoie une 409 avec un port libre suggéré
   (détection via requête SQL sur `host_ports`).
5. Un paramètre secret est stocké en `${vault://...}` en base, résolu via Harpocrate au lancement,
   et n'apparaît jamais en clair dans aucune colonne.
6. Depuis l'UI je vois le statut live, je consulte les logs par service, et je peux
   stop/restart/down la stack.

---

## 11. Point à confirmer à l'implémentation
- **Mécanisme de migration de schéma** : nommer/réutiliser celui déjà présent dans devpod-ui
  (asyncpg, sans Alembic). Ne pas en introduire un nouveau ; aligner le DDL du §4 dessus.
