# Tester mon développement — Procédure optimisée

## Stack dev : `test1` — installée le 30/08/2026

Alias SSH `test1` → `root@192.168.10.250` = **`host-105-1`**. VM de test générée
par le portail le 26/08 pour le workspace `devpod` (`node_list` → `origin:
generated`, `ephemeral: true`). 4 vCPU, 8 Go RAM, 43 Go disque.

| Service | Accès | Note |
|---------|-------|------|
| Portal | `http://192.168.10.250:8081` | bypass Caddy ; `/health` → `{"status":"ok"}` |
| Caddy | `http://192.168.10.250:8091` | reverse proxy dev |
| PostgreSQL | `192.168.10.250:5433` | schéma à `head` (Alembic 118) |
| Grafana | `http://192.168.10.250:3002` | 3001 laissé libre |
| Loki | `192.168.10.250:3100` | de la stack dev, distinct de celui de prod |
| VictoriaMetrics | `192.168.10.250:8428` | idem |
| Termix | `http://192.168.10.250:8087` | |
| Browserless | `http://192.168.10.250:3000` | **préexistant**, Chromium headless, aucun token |
| Postgres de test | `192.168.10.250:55432` (`pg-tests`) | **préexistant**, base jetable |

Installation : projet compose `wsportal-dev`, `DATA_ROOT=/data-portal-dev`,
`APP_DIR=/opt/workspace-portal-dev`, branche `dev`. Les services préexistants de
la VM (Browserless, `pg-tests`, les deux Alloy du portail) sont intacts : projet
compose distinct, `DATA_ROOT` dédié, aucun port en commun.

Auth : **locale uniquement** (`oidc_enabled: false`). `LOCAL_USER` /
`LOCAL_PASSWORD` et `VAULT_DEV_PIN` sont dans `/data-portal-dev/.env` — tous
générés par le script, aucun secret externe requis, rien à recopier ici.

> ⚠️ **Cette VM est éphémère et liée au workspace `devpod`.** Une suppression
> depuis l'UI du portail l'efface en dix secondes, stack comprise — c'est arrivé
> le 30/08 à une VM `test2` détruite trois minutes après sa création, en plein
> build. Une stack installée à la main n'est pas connue du portail : elle part
> avec la machine, sans trace. Réinstaller = rejouer § Installer la stack dev.

> **Un alias SSH qui répond ne prouve rien.** Les alias sont recyclés : `test1` a
> désigné trois machines différentes en un mois, et `test2` deux. Vérifier ce
> qu'il y a *derrière* l'alias avant tout déploiement :

```bash
ssh test1 "hostname; ls -d /opt/*portal* 2>/dev/null || echo 'PAS DE STACK PORTAIL'; \
           docker ps --format '{{.Names}}'"
```

### Cibles mortes — ne pas y retourner

| Ancienne cible | État (vérifié le 30/08) |
|---|---|
| `test2` / `192.168.10.219` | supprimée — `No route to host` |
| ancienne `test1` / `192.168.10.196` | supprimée |
| `test2` / `192.168.10.178` (`host-test-107-2`) | créée puis détruite le 30/08, 3 min de vie |

### Prod — `dev.yoops.org` / `192.168.10.164`

Projet compose `deploy`, conteneurs `deploy-<service>-1`. Services vus par
Loki : `portal`, `caddy`, `postgres`, `loki`, `grafana`, `victoriametrics`,
`alloy`, `termix`, `app`, `backend`, `frontend`.

**Pas d'accès SSH depuis un workspace** (`publickey` refusé en `debian` comme en
`root`) — le déploiement est une action du pilote, pas de l'agent.


---

## Vérifier la prod sans SSH — depuis n'importe quel workspace

C'est le chemin qui a validé le correctif `reconcile_port_forward` le 30/08 : le
LAN est joignable en HTTP même sans SSH. À privilégier sur toute déduction.

| Endpoint | Sert à |
|---|---|
| `http://192.168.10.164:8080/health` | le portail est-il debout (bypass Caddy) |
| `http://192.168.10.164:3100` | **Loki** — API HTTP, requêtes LogQL directes |
| `http://192.168.10.164:8428` | VictoriaMetrics — `node_*` des VM de test uniquement |
| `http://192.168.10.164:3001` | Grafana |

```bash
# Les N dernières lignes du portail correspondant à un motif
curl -s -G http://192.168.10.164:3100/loki/api/v1/query_range \
  --data-urlencode 'query={role="portail",compose_service="portal"} |~ "reconcile_"' \
  --data-urlencode 'since=1h' --data-urlencode 'limit=50' \
  --data-urlencode 'direction=forward' \
| python3 -c 'import json,sys,datetime
for st in json.load(sys.stdin)["data"]["result"]:
  for ts,l in st["values"]:
    print(datetime.datetime.fromtimestamp(int(ts)/1e9).strftime("%H:%M:%S"), l.strip())'
```

Interroger Loki en HTTP plutôt que par l'outil MCP quand il faut **attendre**
un événement : ça permet une boucle de surveillance qui notifie à l'arrivée de
la ligne, au lieu de sonder à l'aveugle.

Surveiller un redéploiement = guetter `Started server process`, puis la ligne
métier attendue. **Toujours inclure les motifs d'échec dans le filtre**
(`Traceback`, `*_failed`, `*_not_found`) et un battement périodique : sinon un
déploiement qui n'a jamais eu lieu est indiscernable d'un déploiement réussi.

---

## Installer la stack dev (première installation, ou après destruction de la VM)

Rejouable telle quelle sur toute VM avec Docker et un `/opt` libre — c'est la
commande qui a installé la stack de `test1` le 30/08. Vérifier d'abord que les
ports voulus sont libres (`ss -tln`) :

```bash
ssh <cible>
git clone -b dev https://github.com/gaelgael5/devpod-ui.git /opt/workspace-portal-dev
export DATA_ROOT=/data-portal-dev COMPOSE_PROJECT_NAME=wsportal-dev \
       PORTAL_DEV_PORT=8081 POSTGRES_DEV_PORT=5433 CADDY_DEV_PORT=8091 \
       GRAFANA_DEV_PORT=3002 APP_DIR=/opt/workspace-portal-dev
bash /opt/workspace-portal-dev/scripts/dev-deploy.sh dev
```

Défauts du compose dev si les variables ne sont pas posées : portail `8080`,
Postgres `5432`, Caddy `80`, Loki `3100`, Grafana `3001`. **Sur une VM partagée,
toujours décaler** — `3000` est pris par Browserless, `80` par un Caddy de prod.
`COMPOSE_PROJECT_NAME` évite la collision avec un autre projet du même
répertoire `deploy`. Sur une VM qui héberge autre chose, ne jamais toucher
`/data` : utiliser un `DATA_ROOT` dédié.

**Ce qu'une stack neuve ne peut PAS montrer.** La base est vide : aucun
workspace `running`, donc les chemins qui itèrent dessus ne produisent
strictement aucun log — `reconcile_port_forwards` n'émet ni
`reconcile_port_forward` ni `reconcile_devpod_state_missing`. Vérifier ce genre
de comportement demande en plus un nœud enrôlé en mTLS et un workspace créé sur
cette stack. Le mesurer d'avance évite de conclure « ça marche » sur un silence.

---

## Cycle standard : écrire → tester → corriger

```bash
# 1. Lint + types + tests, localement
cd backend && uv run ruff check src/ tests/ && uv run mypy src/ && uv run pytest -q

# 2. Pousser sur dev
git push origin dev

# 3. Déployer sur test1 — le script fait pull + build + restart + migrations
ssh test1 "export DATA_ROOT=/data-portal-dev COMPOSE_PROJECT_NAME=wsportal-dev \
  PORTAL_DEV_PORT=8081 POSTGRES_DEV_PORT=5433 CADDY_DEV_PORT=8091 GRAFANA_DEV_PORT=3002 \
  APP_DIR=/opt/workspace-portal-dev
bash /opt/workspace-portal-dev/scripts/dev-deploy.sh dev"

# 4. Lire les vrais logs
ssh test1 "docker logs wsportal-dev-portal-1 --tail=100"

# 5. Tester via curl ou Browserless
curl -s http://192.168.10.250:8081/health
```

`dev-deploy.sh` est un shim qui délègue à `scripts/deploy-portal.sh` (script de
déploiement **unique** : pull, install.sh, .env, build, **migrations Alembic**,
smoke) avec le compose de dev. Il est **idempotent** et **auto-mis à jour**
(ré-exécution si le dépôt a changé au pull). Ne jamais faire `git pull`
manuellement sur la VM — le script le fait.

Cookies : ils portent le domaine `yoops.org`. Pour l'API en curl, utiliser
`--resolve dev.yoops.org:8081:192.168.10.250` et l'URL `http://dev.yoops.org:8081` — un
curl sur l'IP ne renverra jamais le cookie. Auth locale : `LOCAL_USER` /
`LOCAL_PASSWORD` du `.env` de la stack via `POST /auth/local-login` ; PIN vault :
`VAULT_DEV_PIN` du même fichier.

---

## Règle fondamentale : le workflow EST l'environnement de test

**Ne jamais simuler l'environnement avec `docker run --rm python -c '...'`.**

Ces commandes n'ont pas le même réseau, le même `.env`, le même cycle de vie
uvicorn, ni le même contexte lifespan que la vraie stack. Elles produisent des
résultats qui ne se reproduisent pas dans le vrai service — c'est précisément ce
qu'on cherche à éviter.

Corollaire quand aucune stack de test n'est disponible : le repli n'est pas la
simulation, c'est le **test qui verrouille le comportement** (fixtures + assert
sur la branche prise), doublé de la vérification en prod par les logs. Un test
qui passe aussi bien avec qu'après le correctif ne prouve rien : le vérifier en
remettant le bug, avant de le committer.

---

## Diagnostic d'un bug en production (ordre des actions)

### 1. Lire les vrais logs en premier

Depuis un workspace, sans SSH — Loki (voir plus haut), ou l'outil MCP
`logs_query`. Sur la machine :

```bash
docker logs deploy-portal-1 --tail=200 2>&1     # prod
docker logs wsportal-dev-portal-1 --tail=200    # stack dev
```

Chercher d'abord la **branche non prise** : un chemin sain qui n'apparaît jamais
dans les logs est un aussi bon signal qu'une erreur — c'est ce qui a révélé le
`devpod up` rejoué à chaque redémarrage (`reconcile_port_forward` absent des
logs sept jours durant).

### 2. Si le crash est silencieux (pas de traceback) : instrumenter

Ajouter des `log.info("lifespan_step", step="nom_etape")` dans le code suspect —
notamment dans le lifespan de `app.py`. Puis : **pousser → déployer → relire**.
Le dernier log avant le crash indique l'étape fautive.

### 3. Si le process hang (pas de crash, pas de log) : py-spy

```bash
docker exec deploy-portal-1 ps aux | grep python
docker exec deploy-portal-1 py-spy dump --pid <PID>
```

### 4. Charge d'un nœud

Les métriques `node_*` de VictoriaMetrics ne couvrent **que** les VM de test
(`host-105-1`, `host-106-1`) : ni la prod, ni les nœuds de workspaces. Sur une
machine non instrumentée, mesurer à la main — `uptime` pour la charge, et le
temps CPU **système** cumulé par processus, qui distingue un travail réel d'une
boucle folle :

```bash
ps -eo pid,etimes,time,args --sort=-time | head
awk '{print "utime",$14,"stime",$15}' /proc/<pid>/stat   # deux fois, comparer le delta
```

### 5. Inspecter la DB

```bash
docker exec deploy-postgres-1 psql -U "$POSTGRES_USER" portal -c 'SELECT * FROM global_config;'
```

---

## Tests UI autonomes avec Browserless

`ghcr.io/browserless/chromium`, sur `test1` : `http://192.168.10.250:3000`,
aucun token. Permet de tester l'interface sans intervention humaine.

```bash
# Screenshot
curl -s -X POST http://192.168.10.250:3000/screenshot \
  -H "Content-Type: application/json" \
  -d '{"url": "http://<portail>/health", "options": {"fullPage": true}}' -o /tmp/screen.png

# Interaction scriptée
curl -s -X POST http://192.168.10.250:3000/function \
  -H "Content-Type: application/json" \
  -d '{"code": "async ({ page }) => { await page.goto(\"http://<portail>\"); await page.waitForSelector(\"#app\", { timeout: 5000 }); return { title: await page.title() }; }"}'
```

L'image `/tmp/screen.png` se lit ensuite avec le tool `Read`.

Browserless tourne sur une VM de test **liée à un workspace** : elle peut
disparaître avec lui. Vérifier qu'il répond avant de bâtir un test dessus.

---

## Ajouter un service temporaire à la stack de test

1. Ajouter le service dans `deploy/docker-compose.dev.yml` avec `networks: [internal]`
2. Pousser + relancer `dev-deploy.sh` — le service démarre avec le reste
3. Le nommer explicitement pour éviter toute confusion avec la stack de prod

```yaml
  mock-oidc:
    image: ghcr.io/navikt/mock-oauth2-server:latest
    networks:
      - internal
    environment:
      SERVER_PORT: "8888"
```

Le portail l'atteint via `http://mock-oidc:8888` sur le réseau interne.

---

## Entretien de ce document

Il a menti pendant un mois : il décrivait une VM détruite et un alias recyclé,
et une session entière est partie déployer dans le vide. À corriger **le jour
où** une VM de test est créée ou détruite, dans le même passage — pas « plus
tard ». Chaque IP, port et nom de conteneur écrit ici doit avoir été vérifié par
une commande, jamais recopié de mémoire ; dater ce qui est daté.
