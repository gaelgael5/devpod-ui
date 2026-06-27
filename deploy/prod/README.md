# Déploiement PRODUCTION — workspace-portal

Procédure de mise en production du portail sur une VM dédiée (pve2), avec TLS
wildcard DNS-01 Cloudflare. Miroir durci de la procédure `dev` :
`dev-deploy.sh` → `deploy/prod/prod-deploy.sh`.

## Contenu de ce répertoire

| Fichier | Rôle |
|---|---|
| `docker-compose.prod.yml` | Stack prod : `postgres` + `portal` + `caddy` (TLS). Aucun port DB/workspace publié. |
| `Caddyfile.prod` | Reverse-proxy TLS DNS-01 Cloudflare sur `{$BASE_DOMAIN}`. |
| `.env.prod.example` | Gabarit du `/data/.env` prod (`DEV_MODE=false`, `BASE_DOMAIN=pod.yoops.org`). |
| `prod-deploy.sh` | Script de déploiement / mise à jour autonome (root, sur la VM). |

## Différences clés avec la dev

- **TLS** : Caddy compilé avec le plugin Cloudflare (`Dockerfile.caddy`), ports **80 + 443**,
  certificats obtenus en DNS-01 (token `CF_API_TOKEN`).
- **Surface réseau réduite** : Postgres (`5432`) et la plage workspace (`40000-40019`) ne
  sont **pas** publiés sur l'hôte — tout transite par Caddy + OIDC.
- **`DEV_MODE=false`** : cookie de session `https_only`.
- **`PORTAL_VAULT_KEK`** généré une seule fois (obligatoire en prod).
- Branche cible par défaut : **`main`** (la dev déploie `dev`).

## Procédure

### 1. Provisionner la VM prod (sur le host PVE, en root)

Réutilise le script générique de clonage (mêmes paramètres que la dev, nom/IP adaptés) :

```bash
curl -sSL https://raw.githubusercontent.com/gaelgael5/devpod-ui/refs/heads/main/scripts/proxmox-clone-vm-node.sh \
  | bash -s -- <VMID> --name portail-prod --template 9000 --storage vmpool \
      --ip <IP/CIDR> --gw <GATEWAY>
```

### 2. Premier déploiement (sur la VM, en root)

```bash
git clone https://github.com/gaelgael5/devpod-ui.git /opt/workspace-portal
cd /opt/workspace-portal
./deploy/prod/prod-deploy.sh main
```

Au premier lancement, le script génère automatiquement les secrets internes
(`POSTGRES_*`, `DATABASE_URL`, `SESSION_SECRET_KEY`, `PORTAL_VAULT_KEK`,
`LOCAL_PASSWORD`) et affiche les credentials **une seule fois** — les noter.

### 3. Renseigner les credentials externes

Éditer `/data/.env` (non régénérés car non auto-générables) :

```dotenv
CF_API_TOKEN=<token Cloudflare, droit « Edit zone DNS » sur yoops.org>
OIDC_CLIENT_SECRET=<secret du client Keycloak workspace-portal>
ACME_EMAIL=admin@yoops.org
```

Prérequis externes : enregistrement DNS `pod.yoops.org` (et `*.pod.yoops.org`)
routé vers la VM (Cloudflare Tunnel), client OIDC `workspace-portal` configuré
dans le realm `yoops`.

Puis relancer pour activer TLS + OIDC :

```bash
./deploy/prod/prod-deploy.sh main
```

### 4. Mises à jour ultérieures

```bash
cd /opt/workspace-portal && ./deploy/prod/prod-deploy.sh main
```

Le script fait `git pull --ff-only`, se ré-exécute s'il a lui-même changé,
rebuild, redémarre la stack, applique les migrations Alembic, puis vérifie le
healthcheck du conteneur `portal`. Les secrets déjà présents dans `/data/.env`
ne sont **jamais** réécrits.

## Exploitation

```bash
# Logs
docker compose -f deploy/prod/docker-compose.prod.yml logs -f portal
docker compose -f deploy/prod/docker-compose.prod.yml logs -f caddy

# État
docker compose -f deploy/prod/docker-compose.prod.yml ps
```
