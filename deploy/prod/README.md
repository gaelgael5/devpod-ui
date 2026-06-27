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

#### Créer le token Cloudflare (`CF_API_TOKEN`)

`CF_API_TOKEN` permet à Caddy d'obtenir automatiquement un certificat TLS wildcard
(`*.pod.yoops.org`) via le challenge **DNS-01 Let's Encrypt** : Caddy crée
temporairement un enregistrement `_acme-challenge` via l'API Cloudflare, Let's
Encrypt le vérifie, puis Caddy le supprime.

1. Se connecter sur **dash.cloudflare.com** avec le compte qui gère `yoops.org`.
2. En haut à droite : profil → **My Profile** → onglet **API Tokens**.
3. Cliquer **Create Token** → template **"Edit zone DNS"** → **Use template**.
4. Dans *Zone Resources* : `Include → Specific zone → yoops.org`.
5. **Continue to summary** → **Create Token**.
6. Copier la valeur affichée (**elle ne s'affiche qu'une seule fois**).

Injecter le token sans relancer le script complet :

```bash
TOKEN="<valeur_du_token>"
sed -i "s|^CF_API_TOKEN=.*|CF_API_TOKEN=${TOKEN}|" /data/.env
docker compose -f /opt/workspace-portal/docker-compose.prod.yml up -d
```

> **Important** : utiliser `up -d` et non `restart` — `restart` ne relit pas
> le `env_file`, `up -d` recrée les conteneurs avec les nouvelles variables.

Caddy tente alors d'obtenir le certificat via DNS-01. Vérifier les logs :

```bash
docker compose -f /opt/workspace-portal/docker-compose.prod.yml logs -f caddy
```

Un déploiement réussi se termine par :

```
certificate obtained successfully   identifier=pod.yoops.org
```

Prérequis externes : DNS `pod.yoops.org` + `*.pod.yoops.org` routés vers la VM
via Cloudflare Tunnel (voir ci-dessous), client OIDC `workspace-portal` configuré
dans le realm `yoops`.

#### Exposer la VM via Cloudflare Tunnel

Le portail s'expose via un tunnel cloudflared **existant** (machine dédiée).
Ajouter les règles suivantes dans son `config.yml` (avant le wildcard `*.yoops.org`) :

```yaml
  - hostname: pod.yoops.org
    service: https://<IP_VM>:443
    originRequest:
      noTLSVerify: true
      originServerName: pod.yoops.org
  - hostname: "*.pod.yoops.org"
    service: https://<IP_VM>:443
    originRequest:
      noTLSVerify: true
      originServerName: pod.yoops.org
```

Remplacer `<IP_VM>` par l'IP de la VM sur le réseau interne. Recharger :

```bash
systemctl restart cloudflared
```

> `noTLSVerify` + `originServerName` : cloudflared se connecte à Caddy via IP,
> Caddy utilise son cert Let's Encrypt pour `pod.yoops.org` — le SNI doit
> correspondre même si la vérification du certificat est ignorée.

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
