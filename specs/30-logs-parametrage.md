# SPEC — Paramétrage de la stack de logs (devpod-ui)

> Fonctionnalité : doter devpod-ui d'une **stack de logs autonome** (collecteurs Alloy →
> Loki → Grafana), embarquée dans le produit et pilotée par une **unique section de config**.
> Repo : `gaelgael5/devpod-ui` — branche `dev` — commits conventionnels en français.
>
> Références : `02_CONFIG_REFERENCE.md` (config globale), `26-compose-gallery.md` (galerie
> compose, modèle `ComposeTemplate`), `docs/logs.md` (collecteur Alloy, réf `agflow.docker`),
> `deploy/docker-compose.yml` (stack de déploiement du portail).

---

## 1. Contexte & modèle

devpod-ui est un **produit autonome**. Il n'emprunte pas la stack `agflow-logs` (LXC 116) :
il embarque **sa propre** chaîne de logs. Aujourd'hui elle cohabite sur le host de dev ;
demain elle tourne sur une machine dédiée qui héberge tout (portail + hosts workspace +
serveurs de test). Le pattern collecteur est celui d'`agflow.docker`, mais **la cible de
push appartient à devpod-ui** et est configurable.

Deux rôles à ne pas confondre :
- **Central** (Loki + Grafana) : singleton stateful → vit dans la stack de déploiement du
  portail (`deploy/`). Jamais un template de galerie (sinon on lancerait N Loki).
- **Collecteur** (Alloy) : répliqué, jetable → un par host, pousse vers le central.

### Décisions déjà tranchées (ne pas re-débattre)
1. **On duplique** la stack de logs dans devpod-ui (produit autonome). Pas de dépendance
   à `agflow-logs`.
2. **Un seul point de paramétrage** : la section `logs:` du `config.yaml` global (§2).
   Un seul champ (`loki_push_url`) bouge entre déploiement homelab et machine dédiée.
3. **Loki n'a pas de backend SQL.** Son stockage est un volume (object store + index TSDB).
   Le Postgres mutualisé du host ne sert **qu'à Grafana** (config/dashboards/users).
4. **Interpolation native uniquement** (`${VAR}` + `.env`), conformément à `26-compose-gallery`
   §2.1. Les variables du collecteur sont injectées par le portail, pas saisies par l'user.
5. **Chaque collecteur porte un `role`** (`portail` | `workspace` | `test`), en plus de `host`
   et `module`. Permet de filtrer une classe entière de hosts dans Grafana sans énumérer les
   noms. Cohérent avec le champ `role` relevé pour l'audit `node_list` (`27`/`28`).

---

## 2. Paramétrage central — section `logs:` du `config.yaml` global

Nouvelle section admin-only, au même niveau que `caddy` / `cloudflare_manager`. Validée
pydantic v2 `extra="forbid"`.

```yaml
logs:
  enabled: true
  loki_push_url:  "http://192.168.10.<host-stack>:3100/loki/api/v1/push"  # cible des collecteurs
  loki_query_url: "http://loki:3100"                                       # lu par la primitive MCP
  grafana_url:    "https://log.dev.yoops.org"                              # lien portail + deep-links
  module:         "devpod"                                                 # label `module` commun
  push_token:     "${vault://logs/loki_push_token}"                        # optionnel (Loki protégé)
```

**Deux URLs Loki distinctes, volontairement** — point de conception à retenir :
- `loki_push_url` doit être **routable depuis TOUS les hosts**, y compris les serveurs de
  test distants → IP/host joignable sur le réseau, pas un nom de service Docker interne.
- `loki_query_url` est consommée par la primitive MCP qui tourne **dans** le portail → peut
  être le nom de service interne (`loki:3100`, réseau `internal`).

`enabled: false` ⇒ le portail n'injecte aucun collecteur, masque le lien de navigation (§5)
et n'expose pas la primitive MCP (§6). Permet de désactiver proprement la chaîne.

Modèle pydantic (indicatif) :
```python
class LogsConfig(BaseModel):
    model_config = {"extra": "forbid"}
    enabled: bool = False
    loki_push_url: str | None = None
    loki_query_url: str | None = None
    grafana_url: str | None = None
    module: str = "devpod"
    push_token: str | None = None   # littéral ou ${vault://...}/${env://...}
```

---

## 3. Le collecteur Alloy (docker compose)

Aligné sur `docs/logs.md` / `agflow.docker`. **Deux sources de collecte** : conteneurs Docker
(via socket) **et** système du host (journald).

### 3.1 Compose du collecteur
```yaml
services:
  alloy:
    image: grafana/alloy:v1.5.1
    container_name: devpod-alloy-agent
    restart: unless-stopped
    command:
      - run
      - /etc/alloy/config.alloy
      - --storage.path=/var/lib/alloy/data
      - --server.http.listen-addr=0.0.0.0:12345
    environment:
      LOKI_URL: ${LOKI_URL:?LOKI_URL requis}
      HOSTNAME: ${HOSTNAME:?HOSTNAME requis}
      MODULE:   ${MODULE:-devpod}
      ROLE:     ${ROLE:?ROLE requis}          # portail | workspace | test
    volumes:
      - ./config.alloy:/etc/alloy/config.alloy:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /var/log:/var/log:ro
      - /run/log/journal:/run/log/journal:ro
      - /etc/machine-id:/etc/machine-id:ro
      - alloy_data:/var/lib/alloy/data
volumes:
  alloy_data:
```

`config.alloy` (résumé — cf. réf pour le détail River) :
- **Source 1 — conteneurs** : `discovery.docker` (socket) + relabel → labels `container`,
  `compose_service`, `compose_project`.
- **Source 2 — système du host** : `loki.source.journal` (/run/log/journal) → labels `unit`,
  `host`. **Indispensable** : capte le kernel, systemd, sshd et surtout le **daemon Docker** —
  donc les échecs qui surviennent *avant* qu'un conteneur démarre (`docker compose up` qui
  échoue, host qui ne répond plus). Sans journald, un serveur de test en panne au boot est un
  angle mort total.
- **Sortie** : `loki.write` vers `env("LOKI_URL")`,
  `external_labels = { host = env("HOSTNAME"), module = env("MODULE"), role = env("ROLE") }`.
  Ces labels s'appliquent aux **deux** sources.
- Cardinalité : ces labels sont basse cardinalité ; tout identifiant volatil reste dans la
  ligne (filtrage LogQL `| json | ...`).

### 3.2 Variables de contexte injectées par le portail
`LOKI_URL`, `HOSTNAME`, `MODULE`, `ROLE` ne sont **pas** des `parameters` de galerie
(formulaire). Ce sont des **variables de contexte** que le portail ajoute au `.env` généré au
lancement (`26-compose-gallery` §5, étape 4), en plus des `env_values` user :

| Variable   | Source                                                                 |
|------------|------------------------------------------------------------------------|
| `LOKI_URL` | `logs.loki_push_url` (config globale)                                   |
| `MODULE`   | `logs.module`                                                          |
| `HOSTNAME` | `name` du host cible (déjà connu du portail)                           |
| `ROLE`     | nature du host cible, dérivée par le portail : `portail` \| `workspace` \| `test` |

**Évolution galerie** : le générateur de `.env` accepte un jeu de variables de contexte
fournies par le portail, distinctes des params user. Bénéficie à tout template infra.

Le `ROLE` réutilise la même taxonomie que le champ `role` proposé pour `node_list` (audit MCP)
— une seule notion de rôle de host, cohérente entre l'observabilité et la découverte.

### 3.3 Le collecteur comme template `builtin` (résout le blocage bind-mount)
La validation galerie interdit les bind-mounts absolus. Or le collecteur monte `docker.sock`,
`/var/log`, `/run/log/journal`, `/etc/machine-id`. Décision, en réutilisant l'enum existant
`ComposeTemplate.source` :
- Un template **`source=builtin`** (fourni par le produit) peut déclarer des bind-mounts
  d'une **whitelist système en lecture seule** : `/var/run/docker.sock`, `/var/log`,
  `/run/log/journal`, `/etc/machine-id`. Tout autre bind-mount absolu reste refusé.
- Les templates **`source=user`** conservent l'interdiction totale (inchangé).
Le collecteur est donc livré comme template `builtin` « Collecteur de logs (Alloy) »,
lançable en un clic sur un host de test, ou embarqué au provisioning (profil de test, hors
périmètre de cette spec).

---

## 4. Loki + stockage dans la stack du portail (`deploy/`)

Ajout de deux services (`loki`, `grafana`) aux composes de déploiement, réseau `internal`.
En **dev** (`docker-compose.dev.yml`), ils cohabitent avec le service `postgres` déjà présent
(base `portal`) — c'est ce que montre le schéma. En **prod** (`docker-compose.yml`), Postgres
est externe au compose (voir cible ci-dessous).

- **`loki`** : `grafana/loki:3.3.2` (tag épinglé — pas de `:latest`), config file montée,
  volume **`loki_data`** → à faire pointer sur un **dataset ZFS** (compression + snapshots).
  Rétention 720h (30 j) via compactor. Object store filesystem. **Aucun Postgres.**
- **`grafana`** : `grafana/grafana:11.4.0`, datasource Loki provisionnée, backend de config
  **sur l'instance Postgres du déploiement**, dans une base `grafana` dédiée (distincte de
  `portal`) — `GF_DATABASE_TYPE=postgres`, `GF_DATABASE_HOST`, `GF_DATABASE_NAME=grafana`, etc.
  Auth **Keycloak SSO** (realm `yoops`, client `grafana`).

### 4.1 Stockage (rappel explicite)
Les *processus* Loki/Grafana tournent dans le Docker du portail, mais leurs *données* sont
ailleurs : **Loki → volume `loki_data` (dataset ZFS)** ; **Grafana → Postgres** (base `grafana`).
Aucune donnée de logs ne vit dans le conteneur.

### 4.2 Exposition réseau (point critique)
Pour recevoir les push des hosts distants (Test/Host), **Loki doit être joignable hors du
réseau `internal`** — un service seulement sur le bridge interne ne recevrait rien.
- **Défaut (réseau de confiance / homelab)** : publier le port `3100` sur le host de la stack
  (`ports: ["3100:3100"]`), push en HTTP direct — c'est ce que fait la réf `docs/logs.md`.
  `loki_push_url` = `http://<host-stack>:3100/loki/api/v1/push`.
- **Durcissement (machine dédiée / réseau exposé)** : route Caddy dédiée (TLS ACME, pattern
  `deploy/` existant) + `push_token` (§2) porté en `Authorization` par le collecteur.
  `loki_push_url` = `https://loki.dev.yoops.org/loki/api/v1/push`.

Grafana, lui, s'expose via Caddy à l'URL `logs.grafana_url` (TLS + SSO Keycloak). Ces services
ne tournent **que** sur le host qui porte la stack, jamais répliqués.

> **Cible Postgres de Grafana**, en miroir du pattern dev/prod existant :
> - **dev** : Postgres est un service de la stack → `GF_DATABASE_HOST=postgres:5432` sur le
>   réseau `internal`. Aucun host-gateway nécessaire.
> - **prod** : Postgres externe au compose → `GF_DATABASE_HOST` = l'adresse déjà utilisée par
>   le portail dans `/data/.env`.
> Dans les deux cas, créer la base `grafana` sur cette instance (le portail utilise `portal`).

---

## 5. Évolutions du portail — navigation vers la visualisation

Le portail expose un point d'entrée **« Logs »** qui ouvre `logs.grafana_url` dans un nouvel
onglet (`target="_blank"`). Pas d'iframe (auth/CSP/thème), un simple lien — Grafana gère son
propre SSO Keycloak, l'utilisateur du realm `yoops` est déjà authentifié.

Deep-links contextuels : là où c'est utile, le lien pré-remplit une requête Grafana Explore.
- Niveau **host** (vue Docker hosts) → `{host="<name>"}`
- Niveau **classe de hosts** → `{role="test"}` (tous les serveurs de test d'un coup)
- Niveau **déploiement compose** → `{compose_project="<deployment_id>"}`
- Niveau **workspace** → `{compose_project="<workspace>"}` (selon le stamping des labels)

Le format d'URL Explore (`panes`/`left` encodé) dépend de la version de Grafana → à caler
sur la version déployée ; **fallback** = lien nu vers `grafana_url` + `/explore` avec la
datasource Loki présélectionnée. Si `logs.enabled=false`, le point d'entrée est masqué.

---

## 6. Branchement de la primitive MCP `logs_query`

La primitive (spec dédiée `mcp-logs-query.md`) est enregistrée dans la surface MCP du portail.
Elle consomme la section `logs:` :
- interroge `logs.loki_query_url` (`/loki/api/v1/query_range`) ;
- compose le `grafana_url` de retour à partir de `logs.grafana_url` (bascule agent → humain) ;
- applique `push_token` si présent (auth Loki).

Filtres alignés sur les labels du collecteur, `role` inclus (`node`/`role`/`workspace`/
`service`/`level`) + échappatoire LogQL. Read-only, comportement d'échec explicite
(`logs_backend_unreachable`), conforme à `27-convention-descripteurs-mcp.md`. Si
`logs.enabled=false`, la primitive n'est pas exposée (ou renvoie une erreur explicite).

---

## 7. Contraintes & conventions
- pydantic v2 `extra="forbid"` partout ; asyncpg en direct (pas de SQLAlchemy/Alembic).
- Fichiers source ≤ 300 lignes ; logs JSON structurés (structlog).
- Pas de `:latest` (lint galerie + services `deploy/`).
- Interpolation native `${VAR}` + `.env` ; aucun dialecte de templating maison.
- Secrets uniquement en `${vault://...}` / `${env://...}` (résolveur §Config-Reference).
- Commits conventionnels en français, sur `dev`.

## 8. Critères d'acceptation
1. Une section `logs:` valide le chargement de config ; `enabled:false` neutralise collecteur,
   lien et primitive sans erreur.
2. Lancer le template `builtin` « Collecteur de logs » sur un host de test génère un `.env`
   avec `LOKI_URL`/`HOSTNAME`/`MODULE`/`ROLE` **injectés par le portail** (non saisis), et
   Alloy pousse vers Loki.
3. Les logs **système du host** (journald : daemon Docker, sshd…) remontent dans Loki, pas
   seulement les logs conteneurs — vérifiable en filtrant sur une `unit` systemd.
4. `deploy/docker-compose.yml` démarre `loki` + `grafana` ; Grafana persiste sa config sur
   l'instance Postgres du déploiement (base `grafana`) ; la datasource Loki est provisionnée ;
   Grafana est joignable via Caddy à l'URL `logs.grafana_url`.
5. Loki est **joignable depuis un host distant** (push d'un serveur de test reçu et requêtable).
6. Un bind-mount système est accepté pour un template `source=builtin` et refusé pour `user`.
7. Dans Grafana, `{role="test"}` retourne les logs de tous les serveurs de test sans énumérer
   leurs noms.
8. `logs_query` interroge Loki via `loki_query_url` et retourne les lignes + un `grafana_url`.

## 9. Points à confirmer à l'implémentation
- **Exposition du push endpoint** : port `3100` direct (réseau de confiance) vs route Caddy
  TLS + `push_token` (réseau exposé) — choisir selon l'environnement de déploiement.
- Provenance du `ROLE` côté portail : mapping host → rôle (portail/workspace/test) à partir du
  modèle de hosts + du registre des machines de test générées.
- Création de la base `grafana` sur l'instance Postgres du déploiement (le portail utilise
  `portal`) + rôle dédié — hors migrations asyncpg du portail.
- Cible Postgres de Grafana : service interne `postgres:5432` en dev, adresse externe
  `/data/.env` en prod (Postgres n'est pas dans le compose prod actuel).
- Route Caddy exacte / sous-domaine pour `logs.grafana_url` (et éventuellement `loki_push_url`).
