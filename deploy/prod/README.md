# Déploiement PRODUCTION — workspace-portal

Livraison du portail sur une VM dédiée, **sans code source ni git** sur la VM :
les images sont pré-construites par la CI et publiées sur **GHCR** depuis `main`,
et un script bootstrap télécharge la conf, initialise `/data`, puis tire les
images et démarre la stack.

## Contenu de ce répertoire

| Fichier | Rôle |
|---|---|
| `docker-compose.prod.yml` | Stack prod : `postgres` + `portal` + `caddy`, en `image:` GHCR (aucun build). |
| `Caddyfile.prod` | Reverse-proxy TLS DNS-01 Cloudflare sur `{$BASE_DOMAIN}` (`pod.yoops.org`). |
| `prod-deploy.sh` | Bootstrap de livraison (lancé via `curl … | bash`). |

> Le `/data/.env` n'a pas de gabarit ici : il est généré par `scripts/install.sh`
> (téléchargé par le bootstrap) puis complété avec les variables prod.

## Architecture des images

- La CI (`.github/workflows/docker-build.yml`) build `portal` + `caddy` à chaque push.
- Sur **`main` uniquement**, elle les **pousse** sur :
  - `ghcr.io/gaelgael5/workspace-portal:main`
  - `ghcr.io/gaelgael5/workspace-caddy:main`
- Le `docker-compose.prod.yml` référence ces images (`image:`, pas de `build:`),
  donc `docker compose pull` suffit — pas de code source sur la VM.

### Préalable unique (une fois)

Les packages GHCR sont **privés par défaut**. Pour permettre le `pull` anonyme,
les passer en **Public** dans GitHub → *Packages* → `workspace-portal` /
`workspace-caddy` → *Package settings* → *Change visibility* → Public.

## Procédure

### 1. Provisionner la VM prod (sur le host PVE, en root)

Réutilise le script générique de clonage (docker + outils installés par le template) :

```bash
curl -sSL https://raw.githubusercontent.com/gaelgael5/devpod-ui/refs/heads/main/scripts/proxmox-clone-vm-node.sh \
  | bash -s -- <VMID> --name portail-prod --template 9000 --storage vmpool \
      --ip <IP/CIDR> --gw <GATEWAY>
```

### 2. Livraison (sur la VM, en root) — une seule commande

```bash
curl -sSL https://raw.githubusercontent.com/gaelgael5/devpod-ui/refs/heads/main/deploy/prod/prod-deploy.sh \
  | bash -s --
```

Le script crée `/opt/workspace-portal`, télécharge `docker-compose.prod.yml`,
`Caddyfile.prod` et `install.sh`, initialise `/data` (CA, certs, `config.yaml`,
`.env`), génère les secrets internes (`POSTGRES_*`, `DATABASE_URL`,
`PORTAL_VAULT_KEK`, `LOCAL_PASSWORD`, `SESSION_SECRET_KEY`), tire les images
GHCR, démarre la stack, applique les migrations Alembic, puis vérifie la santé.
Les credentials sont affichés **une seule fois** — les noter.

### 3. Renseigner les credentials externes

Éditer `/data/.env` (variables non auto-générables) :

```dotenv
CF_API_TOKEN=<token Cloudflare, droit « Edit zone DNS » sur yoops.org>
OIDC_CLIENT_SECRET=<secret du client Keycloak workspace-portal>
ACME_EMAIL=admin@yoops.org
```

Prérequis externes : DNS `pod.yoops.org` + `*.pod.yoops.org` routés vers la VM
(Cloudflare Tunnel), client OIDC `workspace-portal` configuré dans le realm `yoops`.

Puis relancer la même commande pour activer TLS + OIDC :

```bash
curl -sSL https://raw.githubusercontent.com/gaelgael5/devpod-ui/refs/heads/main/deploy/prod/prod-deploy.sh \
  | bash -s --
```

### 4. Mises à jour ultérieures

Relancer la même commande : le bootstrap re-télécharge la conf, **pull** la
dernière image `:main` et recrée la stack. Les secrets déjà présents dans
`/data/.env` ne sont **jamais** réécrits.

## Notes

- Surface réseau réduite : Postgres (`5432`) et la plage workspace
  (`40000-40019`) ne sont **pas** publiés — tout transite par Caddy (`80`/`443`).
- `DEV_MODE=false` (cookie de session `https_only`).
- Variables d'override du bootstrap : `REF` (branche/tag, défaut `main`),
  `APP_DIR`, `DATA_ROOT`, `BASE_DOMAIN`.

```bash
# Exploitation
docker compose -f /opt/workspace-portal/docker-compose.prod.yml logs -f portal
docker compose -f /opt/workspace-portal/docker-compose.prod.yml ps
```
