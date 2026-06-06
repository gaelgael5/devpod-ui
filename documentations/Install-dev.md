# Installation environnement DEV — ag-flow.rag

Procédure d'**initialisation** du LXC test (303, `192.168.10.184`) pour le service RAG. À exécuter **une seule fois** par l'opérateur. Les déploiements ultérieurs passent ensuite exclusivement par `dev-deploy.sh` (cf. `CLAUDE.md` § Livraison test).

> Pré-requis côté LXC 303 : Ubuntu 24.04, Docker 29.4.3 + Compose v5.1.3 déjà installés (provisionnement Proxmox terminé). User applicatif `agflow` avec `sudo NOPASSWD` et groupe `docker`.

---

## Étape 1 — Accès SSH GitHub

Le repo `ag-flow/rag` est privé. Générer une clé SSH dédiée au déploiement, depuis le LXC :

```bash
pct enter 303
# ou : ssh root@192.168.10.184 -i /root/.ssh/lxc-keys/id_ed25519_lxc303

ssh-keygen -t ed25519 -C "rag-deploy@lxc303" -f /root/.ssh/id_ed25519 -N ""
cat /root/.ssh/id_ed25519.pub
```

Ajouter la clé publique sur GitHub :

1. <https://github.com/settings/keys> → **New SSH key**
2. Title : `rag-deploy lxc303`
3. Coller la clé publique → **Add SSH key**

Tester :

```bash
ssh -T git@github.com
# → Hi <user>! You've successfully authenticated...
```

---

## Étape 2 — Cloner le repo dans `/opt/rag`

**Important** : le chemin `/opt/rag` est figé. Le script `dev-deploy.sh` part du principe que le repo est à cet endroit.

```bash
cd /opt
git clone --branch dev git@github.com:ag-flow/rag.git rag
cd rag
./dev-deploy.sh
```

reset
```bash
cd /opt
rm -rf rag
git clone --branch dev git@github.com:ag-flow/rag.git rag
cd rag
./dev-deploy.sh --reset

```

La branche **`dev`** est la seule branche de livraison test — voir `CLAUDE.md` § Livraison test. Ne pas cloner d'autre branche pour cet environnement.

---

## Étape 3 — Configurer le fichier `.env`

```bash
cp .env.example .env  # si .env.example présent dans le repo
nano .env
```

Si `.env.example` n'existe pas encore (premier setup avant le code backend), créer le fichier à la main :

```env
# ─── PostgreSQL ─────────────────────────────────────────────
POSTGRES_USER=rag
POSTGRES_PASSWORD=<générer : openssl rand -base64 32 | tr -d '/+=' | head -c 32>
POSTGRES_DB=rag_config
DATABASE_URL=postgresql://rag:${POSTGRES_PASSWORD}@postgres:5432/rag_config
RAG_POSTGRES_ADMIN_URL=postgresql://rag:${POSTGRES_PASSWORD}@postgres:5432/postgres

# ─── Master key API (administration) ────────────────────────
RAG_MASTER_KEY=<générer : openssl rand -base64 48 | tr '+/' '-_' | tr -d '=' | head -c 48>

# ─── URL publique (pour redirects OIDC callback) ────────────
RAG_PUBLIC_URL=http://192.168.10.184

# ─── Harpocrate (à renseigner manuellement) ────────────────
# Au moins une API key Harpocrate doit être attribuée au service.
# Format : HARPOCRATE_API_TOKEN_<ID>=hrpv_1_...
#          HARPOCRATE_API_URL_<ID>=https://vault.yoops.org
HARPOCRATE_API_TOKEN_RAG=
HARPOCRATE_API_URL_RAG=https://vault.yoops.org

# ─── Divers ─────────────────────────────────────────────────
ENVIRONMENT=dev
LOG_LEVEL=INFO
SYNC_WORKER_POLL_INTERVAL_SECONDS=30
```

Sécurise le fichier :

```bash
chmod 600 .env
```

**Variables critiques à renseigner avant le premier `dev-deploy.sh`** :

| Variable | Comment l'obtenir |
|---|---|
| `POSTGRES_PASSWORD` | À générer aléatoirement |
| `RAG_MASTER_KEY` | À générer aléatoirement |
| `HARPOCRATE_API_TOKEN_RAG` | Créer une API key dans le coffre Harpocrate scopée au wallet RAG, copier le token complet `hrpv_1_*` |

> Ne JAMAIS committer `.env` — il est gitignored. Toute modif se fait directement sur le LXC.

---

## Étape 4 — Premier déploiement

Le bit exécutable de `dev-deploy.sh` est déjà positionné dans l'index git (`100755`) — pas besoin de `chmod` après le clone.

```bash
./dev-deploy.sh
```

Le script :
1. `git pull origin dev`
2. Build les images `rag-backend:latest` + `rag-frontend:latest` (uniquement si les Dockerfiles existent)
3. `docker compose -f docker-compose-dev.yml down/up`

> Tant que les répertoires `backend/` et `frontend/` ne contiennent pas de Dockerfile (phase d'amorçage du projet), le script skip ces builds et démarre uniquement les services tiers (postgres, caddy, pgweb). Le compose tournera proprement dès que l'implémentation arrivera.

---

## Étape 5 — Vérifier

```bash
docker compose -f docker-compose-dev.yml ps
```

Les services doivent être `healthy` :

```
NAME              STATUS    PORTS
rag-postgres      healthy   0.0.0.0:5432->5432/tcp
rag-backend       healthy   0.0.0.0:8000->8000/tcp
rag-frontend      running
rag-caddy         running   0.0.0.0:80->80/tcp
rag-pgweb         running   0.0.0.0:8081->8081/tcp
```

Test rapide :

```bash
curl http://127.0.0.1:8000/health
# → {"status":"ok"}
```

URLs accessibles depuis le LAN :

| Service | URL |
|---|---|
| UI / API derrière Caddy | http://192.168.10.184 |
| API directe (debug) | http://192.168.10.184:8000 |
| pgweb | http://192.168.10.184:8081 |
| Postgres | `psql postgresql://rag:<pass>@192.168.10.184:5432/rag_config` |

Logs :

```bash
docker compose -f docker-compose-dev.yml logs -f backend
docker compose -f docker-compose-dev.yml logs --tail=50 postgres
```

---

## Étape 6 — Workflow ensuite

L'init est terminée. À partir de maintenant, les mises à jour sont **automatiques** via le script :

```bash
cd /opt/rag
./dev-deploy.sh
```

Et l'agent Claude appelle ça à distance via :

```bash
ssh pve "pct exec 303 -- bash -c 'cd /opt/rag && ./dev-deploy.sh'"
```

C'est le **seul** mode de livraison de test. Pas de `scp`, pas de `rsync`, pas de build local poussé à la main.

---

## Dépannage

### Le build backend échoue
Vérifier qu'un `Dockerfile` existe bien dans `backend/`. Tant que le code n'est pas écrit, le build est skippé — normal en phase d'amorçage.

### Postgres `unhealthy`
```bash
docker compose -f docker-compose-dev.yml logs --tail=100 postgres
```
Cause fréquente : `POSTGRES_PASSWORD` absent du `.env`.

### Backend `unhealthy`
```bash
docker compose -f docker-compose-dev.yml logs --tail=100 backend
```
Causes fréquentes : `DATABASE_URL` mal formée, `HARPOCRATE_API_TOKEN_RAG` manquant, `RAG_MASTER_KEY` absent. Le backend log la variable manquante au boot.

### Reset complet de la DB

⚠ Détruit toutes les données (workspaces, vecteurs, jobs) :

```bash
docker compose -f docker-compose-dev.yml down -v
./dev-deploy.sh
```

### Régénérer la clé SSH GitHub
Si la clé est compromise / a expiré : la révoquer côté GitHub, puis re-suivre l'**Étape 1**.

---

## Arborescence cible

```
/opt/rag/
├── .env                          # gitignored — config locale
├── .env.example                  # template versionné
├── docker-compose-dev.yml        # stack de test
├── dev-deploy.sh                 # script de livraison test (idempotent)
├── Caddyfile                     # config reverse proxy
├── backend/                      # FastAPI + asyncpg + indexer + sync worker (à venir)
├── frontend/                     # Vite + React + TS (à venir)
├── specs/                        # specs produit
├── docs/                         # patterns, règles dev, logs
└── CLAUDE.md                     # instructions Claude Code
```

Spec complète du service : [`specs/00-overview.md`](specs/00-overview.md).
Instructions Claude Code : [`CLAUDE.md`](CLAUDE.md).
