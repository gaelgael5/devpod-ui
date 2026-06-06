# M5 — Installation du portail (CA, image, compose) — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Packager le portail en image Docker (DevPod CLI embarqué, zéro secret), fournir `install.sh` qui initialise `/data` (CA, cert client, config, .env), `docker-compose.yml` avec Caddy, et des scripts `backup.sh`/`restore.sh` chiffrés.

**Architecture:** Le portail est stateless — tout l'état persistant est dans `/data` (volume Docker). L'image est générique et sans secret. La CA est générée une seule fois par `install.sh` et ne doit jamais être écrasée. Caddy est construit avec le plugin Cloudflare DNS pour le wildcard TLS DNS-01. Les backups sont chiffrés avec `age` car `/data` contient `ca-key.pem`.

**Tech Stack:** Bash (scripts), Dockerfile (Python 3.12-slim), Caddy 2 + xcaddy + caddy-dns/cloudflare, docker compose v2, `age` (chiffrement backup), `openssl` (génération CA/certs), `shellcheck` (lint bash).

---

## Structure des fichiers

```
deploy/
├── Dockerfile             # Image portail : Python 3.12, DevPod CLI pinné, docker CLI, openssl
├── Dockerfile.caddy       # Caddy custom : xcaddy + caddy-dns/cloudflare (wildcard DNS-01)
├── docker-compose.yml     # portal + caddy, /data monté, .env runtime
├── Caddyfile              # Route racine → portail ; wildcard *.dev.yoops.org (stub M6)
└── .env.example           # Template sans valeurs (commité, jamais de vraies valeurs)
scripts/
├── install-node.sh        # (existant M4 — ne pas modifier)
├── install.sh             # Init /data + CA (§E-25) + cert portal + config.yaml + .env + compose up
├── backup.sh              # tar /data | age encrypt → fichier .tar.gz.age
└── restore.sh             # age decrypt | tar extract + avertissement reconciliation workspaces
```

**Pièges critiques de ce milestone :**
- §E-25 : `install.sh` ré-exécuté NE doit JAMAIS régénérer la CA. Une nouvelle CA invalide tous les nœuds enrôlés.
- §E-26 : `ca-key.pem` perms 600, jamais dans l'image, jamais loggé.
- §D-21 : Zéro secret dans le Dockerfile (`ARG`/`ENV` avec secrets = fuite via `docker history`).
- §F-30 : TLS wildcard `*.dev.yoops.org` nécessite DNS-01 (Cloudflare), pas HTTP-01.
- §F-33 : Caddy valide l'auth OIDC AVANT de proxifier (fail closed). Stub en M5 → 404 sur `*.`.
- §G-35 : `restore.sh` restaure config/CA/clés — PAS les workspaces (ils vivent dans les daemons des nœuds).
- §G-36 : Backup doit être chiffré (age). Un tar en clair = fuite de `ca-key.pem`.

---

## Task 0 : Dockerfile du portail (`deploy/Dockerfile`)

**Files:**
- Create: `deploy/Dockerfile`

> **Note DevPod version :** Avant d'implémenter, exécuter `devpod version` dans l'environnement de build pour connaître la version à pinner. Le plan utilise `0.6.15` — adapter si différent.

- [ ] **Step 1 : Vérifier que le répertoire deploy/ n'existe pas encore**

```bash
ls -la deploy/ 2>/dev/null || echo "deploy/ absent — à créer"
```

Expected: `deploy/ absent — à créer`

- [ ] **Step 2 : Créer deploy/Dockerfile**

```dockerfile
# deploy/Dockerfile
# Image générique du portail workspace — aucun secret embarqué (§D-21)
# Build : docker build -f deploy/Dockerfile -t workspace-portal:latest .
FROM python:3.12-slim

# Version DevPod à pinner — vérifier avec : devpod version
ARG DEVPOD_VERSION=0.6.15

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        openssl \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI uniquement (pas le daemon — §D-21, l'image ne pilote aucun docker locale)
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/debian \
        $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# DevPod CLI pinné — binaire seul, pas de daemon ni plugin (§D-21)
RUN ARCH=$(dpkg --print-architecture) \
    && case "$ARCH" in \
        amd64) DEVPOD_ARCH="linux-amd64" ;; \
        arm64) DEVPOD_ARCH="linux-arm64" ;; \
        *) echo "Architecture non supportée : $ARCH" && exit 1 ;; \
    esac \
    && curl -fsSL \
        "https://github.com/loft-sh/devpod/releases/download/v${DEVPOD_VERSION}/devpod-${DEVPOD_ARCH}" \
        -o /usr/local/bin/devpod \
    && chmod 755 /usr/local/bin/devpod

WORKDIR /app

# Installer les dépendances Python AVANT de copier le code (layer cache)
COPY backend/pyproject.toml backend/README.md ./
COPY backend/src/ ./src/
RUN pip install --no-cache-dir . \
    && rm -rf src/ pyproject.toml README.md

EXPOSE 8080

# Pas d'ENV avec secret — tout vient de /data/.env au runtime
CMD ["uvicorn", "portal.app:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 3 : Vérifier la syntaxe Dockerfile**

```bash
docker build --check -f deploy/Dockerfile . 2>&1 | head -20
```

Si `docker build --check` n'est pas disponible (Docker < 25) :

```bash
# Vérifier manuellement qu'aucun ARG/ENV ne contient de secret
grep -E "^(ARG|ENV)" deploy/Dockerfile
# Expected : seul DEVPOD_VERSION apparaît — aucun OIDC_*, *_KEY, *_SECRET, *_TOKEN
```

Expected: `ARG DEVPOD_VERSION=0.6.15` uniquement.

- [ ] **Step 4 : Committer**

```bash
git add deploy/Dockerfile
git commit -m "feat(M5): Dockerfile portail — Python 3.12, DevPod CLI pinné, docker CLI, zéro secret"
```

---

## Task 1 : Dockerfile Caddy custom (`deploy/Dockerfile.caddy`)

**Files:**
- Create: `deploy/Dockerfile.caddy`

> Caddy 2 standard ne contient pas le plugin DNS Cloudflare requis pour le wildcard DNS-01 (§F-30). On le construit avec `xcaddy`.

- [ ] **Step 1 : Créer deploy/Dockerfile.caddy**

```dockerfile
# deploy/Dockerfile.caddy
# Caddy avec plugin DNS Cloudflare pour wildcard TLS DNS-01 (§F-30)
FROM caddy:2-builder AS builder

RUN xcaddy build \
    --with github.com/caddy-dns/cloudflare

FROM caddy:2

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
```

- [ ] **Step 2 : Vérifier la syntaxe**

```bash
grep -n "xcaddy\|caddy-dns" deploy/Dockerfile.caddy
# Expected : les deux lignes sont présentes
```

- [ ] **Step 3 : Committer**

```bash
git add deploy/Dockerfile.caddy
git commit -m "feat(M5): Dockerfile.caddy avec plugin caddy-dns/cloudflare (wildcard DNS-01 §F-30)"
```

---

## Task 2 : docker-compose.yml + Caddyfile + .env.example (`deploy/`)

**Files:**
- Create: `deploy/docker-compose.yml`
- Create: `deploy/Caddyfile`
- Create: `deploy/.env.example`

- [ ] **Step 1 : Créer deploy/docker-compose.yml**

```yaml
# deploy/docker-compose.yml
# Services : portail + Caddy. Secrets via /data/.env (perms 600, jamais commité).
# Démarrage : docker compose -f deploy/docker-compose.yml up -d

services:
  portal:
    build:
      context: ..
      dockerfile: deploy/Dockerfile
    image: workspace-portal:latest
    restart: unless-stopped
    env_file: /data/.env
    volumes:
      - /data:/data
    networks:
      - internal
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8080/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

  caddy:
    build:
      context: ./
      dockerfile: Dockerfile.caddy
    image: workspace-caddy:latest
    restart: unless-stopped
    env_file: /data/.env
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    ports:
      - "443:443"
      - "80:80"
    networks:
      - internal

networks:
  internal:
    driver: bridge

volumes:
  caddy_data:
  caddy_config:
```

- [ ] **Step 2 : Valider le docker-compose.yml**

```bash
docker compose -f deploy/docker-compose.yml config --quiet && echo "YAML valide"
```

Expected: `YAML valide` (quelques warnings sur /data absent sont acceptables à ce stade).

- [ ] **Step 3 : Créer deploy/Caddyfile**

```caddyfile
# deploy/Caddyfile
# Route principale → portail. Wildcard *.{$BASE_DOMAIN} → stub 404 (routes workspaces ajoutées en M6).
# §F-33 : Caddy valide l'auth AVANT de proxifier (fail closed).

{
    # API admin interne — jamais exposée hors du réseau docker internal
    admin 0.0.0.0:2019
    email {$ACME_EMAIL}
}

# Portail principal : auth OIDC gérée par FastAPI lui-même
{$BASE_DOMAIN} {
    reverse_proxy portal:8080
}

# Wildcard workspaces — routes dynamiques ajoutées par l'API admin en M6
# §F-30 : DNS-01 via Cloudflare pour le wildcard
# §F-33 : stub 404 fail-closed — jamais d'accès sans auth opérationnelle
*.{$BASE_DOMAIN} {
    tls {
        dns cloudflare {$CF_API_TOKEN}
    }
    # STUB M5 — sera remplacé par forward_auth + reverse_proxy en M6
    respond "Workspace introuvable (M6 non encore déployé)" 404
}
```

- [ ] **Step 4 : Créer deploy/.env.example**

```bash
# deploy/.env.example
# Copier en /data/.env, remplir toutes les valeurs, puis chmod 600 /data/.env
# Ce fichier est commité dans le repo SANS valeurs réelles.

# Clé de signature des sessions FastAPI (générer : openssl rand -hex 32)
SESSION_SECRET_KEY=

# OIDC Keycloak
OIDC_CLIENT_SECRET=

# Harpocrate (laisser vide pour le backend inline)
HARPOCRATE_API_KEY=

# Cloudflare Manager
CFM_API_KEY=

# Caddy — DNS-01 wildcard (§F-30)
CF_API_TOKEN=
ACME_EMAIL=admin@example.com

# Domaine de base (ex: dev.yoops.org)
BASE_DOMAIN=dev.yoops.org
```

- [ ] **Step 5 : Vérifier que .env.example ne contient aucune valeur réelle**

```bash
grep -v "^#\|^$\|=\s*$\|=$" deploy/.env.example && echo "ATTENTION : valeurs trouvées" || echo "OK : aucune valeur"
```

Expected: `OK : aucune valeur`

- [ ] **Step 6 : Committer**

```bash
git add deploy/docker-compose.yml deploy/Caddyfile deploy/.env.example
git commit -m "feat(M5): docker-compose.yml + Caddyfile (stub wildcard M6) + .env.example"
```

---

## Task 3 : `scripts/install.sh` (init portail)

**Files:**
- Create: `scripts/install.sh`

> Ce script s'exécute UNE FOIS sur la VM hôte du portail (ou idempotent si ré-exécuté).
> **§E-25 — CRITIQUE :** La CA ne doit JAMAIS être régénérée si elle existe déjà.
> La clé `ca-key.pem` est la racine de confiance de tout le mTLS des nœuds.

- [ ] **Step 1 : Écrire scripts/install.sh**

```bash
#!/usr/bin/env bash
# install.sh — Initialise /data et démarre le portail workspace
# Idempotent : peut être ré-exécuté sans danger.
# §E-25 : la CA n'est JAMAIS régénérée si /data/certs/ca/ca.pem existe.
# Usage : sudo bash scripts/install.sh [--data-root /data] [--compose-file deploy/docker-compose.yml]
set -euo pipefail

# ── Paramètres par défaut ────────────────────────────────────────────────────
DATA_ROOT="${PORTAL_DATA_ROOT:-/data}"
COMPOSE_FILE="${PORTAL_COMPOSE_FILE:-$(dirname "$0")/../deploy/docker-compose.yml}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --data-root)   DATA_ROOT="$2";   shift 2 ;;
        --compose-file) COMPOSE_FILE="$2"; shift 2 ;;
        *) echo "Argument inconnu : $1" >&2; exit 1 ;;
    esac
done

CA_DIR="$DATA_ROOT/certs/ca"
PORTAL_CERT_DIR="$DATA_ROOT/certs/portal"

# ── Outils requis ────────────────────────────────────────────────────────────
echo "==> Vérification des outils requis..."
for cmd in openssl docker; do
    command -v "$cmd" &>/dev/null || { echo "ERREUR : $cmd introuvable" >&2; exit 1; }
done

# ── 1. Structure /data ───────────────────────────────────────────────────────
echo "==> Initialisation de $DATA_ROOT..."
mkdir -p \
    "$DATA_ROOT/logs" \
    "$DATA_ROOT/users" \
    "$DATA_ROOT/routes" \
    "$DATA_ROOT/templates" \
    "$DATA_ROOT/recipes" \
    "$DATA_ROOT/certs/ca" \
    "$DATA_ROOT/certs/portal" \
    "$DATA_ROOT/certs/nodes"
chmod 700 "$DATA_ROOT"

# ── 2. CA — §E-25 : NE JAMAIS régénérer si déjà présente ───────────────────
if [[ -f "$CA_DIR/ca.pem" ]]; then
    echo "==> CA déjà présente — skip (§E-25). Empreinte :"
    openssl x509 -in "$CA_DIR/ca.pem" -noout -fingerprint -sha256
else
    echo "==> Génération de la CA (racine de confiance mTLS)..."
    # EC P-384 : bon équilibre sécurité/performance pour une CA longue durée
    openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-384 \
        -out "$CA_DIR/ca-key.pem" 2>/dev/null
    chmod 600 "$CA_DIR/ca-key.pem"                  # §E-26 — jamais lisible par d'autres
    openssl req -new -x509 \
        -key "$CA_DIR/ca-key.pem" \
        -sha384 \
        -days 3650 \
        -subj "/CN=workspace-portal-ca/O=workspace-portal" \
        -out "$CA_DIR/ca.pem"
    echo "    CA générée. Empreinte :"
    openssl x509 -in "$CA_DIR/ca.pem" -noout -fingerprint -sha256
fi

# ── 3. Cert client portail — si absent → générer et signer par la CA ────────
# Ce cert est présenté par le portail aux daemons Docker mTLS (DOCKER_CERT_PATH)
# Noms de fichiers attendus par le client Docker : ca.pem, cert.pem, key.pem
if [[ -f "$PORTAL_CERT_DIR/cert.pem" ]]; then
    echo "==> Cert client portail déjà présent — skip."
else
    echo "==> Génération du cert client portail..."
    _PORTAL_CSR=""
    _PORTAL_EXT=""
    trap \
        '[[ -n "${_PORTAL_CSR:-}" ]] && rm -f "$_PORTAL_CSR"; [[ -n "${_PORTAL_EXT:-}" ]] && rm -f "$_PORTAL_EXT"' \
        EXIT
    _PORTAL_CSR=$(mktemp --suffix=.csr)
    _PORTAL_EXT=$(mktemp --suffix=.cnf)

    openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-384 \
        -out "$PORTAL_CERT_DIR/key.pem" 2>/dev/null
    chmod 600 "$PORTAL_CERT_DIR/key.pem"

    openssl req -new \
        -key "$PORTAL_CERT_DIR/key.pem" \
        -subj "/CN=workspace-portal-client/O=workspace-portal" \
        -out "$_PORTAL_CSR"

    cat > "$_PORTAL_EXT" <<EXTEOF
[v3_client]
basicConstraints = CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = clientAuth
EXTEOF

    openssl x509 -req \
        -in "$_PORTAL_CSR" \
        -CA "$CA_DIR/ca.pem" \
        -CAkey "$CA_DIR/ca-key.pem" \
        -CAcreateserial \
        -days 1825 \
        -sha384 \
        -extfile "$_PORTAL_EXT" \
        -extensions v3_client \
        -out "$PORTAL_CERT_DIR/cert.pem"

    cp "$CA_DIR/ca.pem" "$PORTAL_CERT_DIR/ca.pem"
    echo "    Cert client portail généré (valide 1825 jours)."
fi

# ── 4. config.yaml initial ───────────────────────────────────────────────────
CONFIG_FILE="$DATA_ROOT/config.yaml"
if [[ -f "$CONFIG_FILE" ]]; then
    echo "==> config.yaml déjà présent — skip."
else
    echo "==> Génération de config.yaml initial..."
    # Valeurs depuis les variables d'environnement ou prompts interactifs
    _prompt_or_env() {
        local var_name="$1" prompt_text="$2" default_val="${3:-}"
        local val="${!var_name:-}"
        if [[ -z "$val" ]]; then
            if [[ -t 0 ]]; then
                read -rp "$prompt_text [$default_val] : " val
                val="${val:-$default_val}"
            else
                val="$default_val"
            fi
        fi
        echo "$val"
    }

    BASE_DOMAIN=$(_prompt_or_env PORTAL_BASE_DOMAIN "Base domain" "dev.yoops.org")
    EXTERNAL_URL=$(_prompt_or_env PORTAL_EXTERNAL_URL "External URL" "https://$BASE_DOMAIN")
    OIDC_ISSUER=$(_prompt_or_env PORTAL_OIDC_ISSUER "OIDC issuer URL" "https://security.yoops.org/realms/yoops")
    OIDC_CLIENT_ID=$(_prompt_or_env PORTAL_OIDC_CLIENT_ID "OIDC client ID" "workspace-portal")

    cat > "$CONFIG_FILE" <<YAML
version: "1"

server:
  listen: "0.0.0.0:8080"
  base_domain: "${BASE_DOMAIN}"
  external_url: "${EXTERNAL_URL}"
  dev_mode: false
  log:
    level: "info"
    format: "json"
    output: ""

auth:
  oidc:
    issuer: "${OIDC_ISSUER}"
    client_id: "${OIDC_CLIENT_ID}"
    client_secret: "\${env://OIDC_CLIENT_SECRET}"
    scopes: ["openid", "profile", "email", "roles"]
    role_claim: "realm_access.roles"
    admin_role: "admin"
    user_role: "dev"
    username_claim: "preferred_username"

secrets:
  backend: "inline"
  harpocrate:
    url: ""
    api_key: "\${env://HARPOCRATE_API_KEY}"
    base_path: "devpod"

devpod:
  binary: "/usr/local/bin/devpod"
  defaults:
    ide: "openvscode"
    idle_timeout: "2h"
    dotfiles: ""
  client_cert_path: "/data/certs/portal"

hosts: []

caddy:
  admin_api: "http://caddy:2019"

cloudflare_manager:
  url: ""
  api_key: "\${env://CFM_API_KEY}"
YAML
    echo "    config.yaml créé. Éditer $CONFIG_FILE pour ajouter les hosts."
fi

# ── 5. /data/.env ─────────────────────────────────────────────────────────────
ENV_FILE="$DATA_ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
    echo "==> .env déjà présent — skip."
else
    echo "==> Génération de /data/.env..."
    SESSION_KEY=$(openssl rand -hex 32)
    cat > "$ENV_FILE" <<ENVEOF
# Généré par install.sh le $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Perms 600 requises — ne JAMAIS commiter ce fichier (§D-21)

SESSION_SECRET_KEY=${SESSION_KEY}
OIDC_CLIENT_SECRET=
HARPOCRATE_API_KEY=
CFM_API_KEY=
CF_API_TOKEN=
ACME_EMAIL=
BASE_DOMAIN=${BASE_DOMAIN:-dev.yoops.org}
ENVEOF
    chmod 600 "$ENV_FILE"
    echo "    .env créé. Compléter les valeurs manquantes (OIDC_CLIENT_SECRET, etc.) avant de démarrer."
fi

# ── 6. Démarrage via docker compose ─────────────────────────────────────────
echo ""
echo "==> Structure /data initialisée. Pour démarrer le portail :"
echo "    1. Vérifier/compléter $ENV_FILE"
echo "    2. docker compose -f $COMPOSE_FILE up -d"
echo ""
echo "Empreinte CA (à noter pour vérification lors de l'enrôlement des nœuds) :"
openssl x509 -in "$CA_DIR/ca.pem" -noout -fingerprint -sha256
```

- [ ] **Step 2 : Rendre exécutable et passer shellcheck**

```bash
chmod +x scripts/install.sh
shellcheck scripts/install.sh
```

Expected: `0 erreurs` (warnings tolérés si justifiés par un commentaire `# shellcheck disable=SC...`).

- [ ] **Step 3 : Vérifier la syntaxe bash**

```bash
bash -n scripts/install.sh && echo "Syntaxe OK"
```

Expected: `Syntaxe OK`

- [ ] **Step 4 : Test d'idempotence CA (§E-25) en sandbox**

```bash
TMPDATA=$(mktemp -d)
PORTAL_DATA_ROOT="$TMPDATA" bash scripts/install.sh --data-root "$TMPDATA" 2>&1 | grep -E "CA|Empreinte"
# Première exécution : génère la CA
FINGERPRINT1=$(openssl x509 -in "$TMPDATA/certs/ca/ca.pem" -noout -fingerprint -sha256)

PORTAL_DATA_ROOT="$TMPDATA" bash scripts/install.sh --data-root "$TMPDATA" 2>&1 | grep -E "CA|Empreinte"
# Deuxième exécution : skip la CA
FINGERPRINT2=$(openssl x509 -in "$TMPDATA/certs/ca/ca.pem" -noout -fingerprint -sha256)

[[ "$FINGERPRINT1" == "$FINGERPRINT2" ]] && echo "§E-25 OK : CA inchangée" || echo "ERREUR : CA modifiée !"
rm -rf "$TMPDATA"
```

Expected: `§E-25 OK : CA inchangée`

- [ ] **Step 5 : Vérifier les permissions (§E-26, §D-24)**

```bash
TMPDATA=$(mktemp -d)
PORTAL_DATA_ROOT="$TMPDATA" bash scripts/install.sh --data-root "$TMPDATA" >/dev/null 2>&1
stat -c "%a %n" "$TMPDATA/certs/ca/ca-key.pem" "$TMPDATA/certs/portal/key.pem" "$TMPDATA/.env"
rm -rf "$TMPDATA"
```

Expected:
```
600 .../ca-key.pem
600 .../key.pem
600 .../.env
```

- [ ] **Step 6 : Committer**

```bash
git add scripts/install.sh
git commit -m "feat(M5): install.sh — init /data, CA idempotente (§E-25), cert portail, config.yaml, .env"
```

---

## Task 4 : `scripts/backup.sh`

**Files:**
- Create: `scripts/backup.sh`

> §G-36 : Le backup DOIT être chiffré. `/data` contient `ca-key.pem` et potentiellement des secrets inline.
> Outil de chiffrement : `age` (plus simple et plus moderne que GPG pour ce cas d'usage).
> Installer `age` : `apt-get install age` (Debian 12+) ou télécharger depuis https://github.com/FiloSottile/age/releases.

- [ ] **Step 1 : Créer scripts/backup.sh**

```bash
#!/usr/bin/env bash
# backup.sh — Sauvegarde chiffrée de /data (§G-36)
# Le backup contient ca-key.pem, clés SSH, secrets inline → chiffrement OBLIGATOIRE.
#
# Pré-requis : age installé (apt-get install age ou https://github.com/FiloSottile/age/releases)
#
# Usage :
#   AGE_RECIPIENT="age1xxx..." BACKUP_DIR=/backup bash scripts/backup.sh
#   AGE_RECIPIENT="age1xxx..." DATA_ROOT=/data  BACKUP_DIR=/backup bash scripts/backup.sh
#
# Variables d'environnement :
#   DATA_ROOT       Racine des données (défaut : /data)
#   BACKUP_DIR      Dossier de destination (défaut : /backup)
#   AGE_RECIPIENT   Clé publique age du destinataire (OBLIGATOIRE)
set -euo pipefail

DATA_ROOT="${DATA_ROOT:-/data}"
BACKUP_DIR="${BACKUP_DIR:-/backup}"

# AGE_RECIPIENT obligatoire — refus explicite (§G-36 : pas de backup en clair)
if [[ -z "${AGE_RECIPIENT:-}" ]]; then
    echo "ERREUR : AGE_RECIPIENT non défini." >&2
    echo "  Générer une paire : age-keygen -o /root/age-backup.key" >&2
    echo "  Puis : export AGE_RECIPIENT=\$(grep 'public key' /root/age-backup.key | awk '{print \$NF}')" >&2
    exit 1
fi

# Vérifier les outils
for cmd in age tar; do
    command -v "$cmd" &>/dev/null || { echo "ERREUR : $cmd introuvable" >&2; exit 1; }
done

mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date -u +%Y%m%d-%H%M%S)
ARCHIVE="$BACKUP_DIR/portal-backup-${TIMESTAMP}.tar.gz.age"

echo "==> Backup de $DATA_ROOT → $ARCHIVE"
echo "    (§G-36 : chiffré avec age pour la clé ${AGE_RECIPIENT:0:20}...)"

# §G-37 : les écritures atomiques garantissent la cohérence des fichiers individuels.
# Aucun quiesce nécessaire si aucune écriture longue n'est en cours.
# tar + age en pipe — aucun fichier intermédiaire en clair sur disque
tar czf - -C "$(dirname "$DATA_ROOT")" "$(basename "$DATA_ROOT")" \
    | age -r "$AGE_RECIPIENT" -o "$ARCHIVE"

ARCHIVE_SIZE=$(du -sh "$ARCHIVE" | cut -f1)
echo "==> Backup terminé : $ARCHIVE ($ARCHIVE_SIZE)"
echo ""
echo "IMPORTANT : ce backup contient ca-key.pem et les secrets inline."
echo "Stocker $ARCHIVE dans un endroit sûr, distinct du serveur."
```

- [ ] **Step 2 : Rendre exécutable et passer shellcheck**

```bash
chmod +x scripts/backup.sh
shellcheck scripts/backup.sh && echo "shellcheck OK"
bash -n scripts/backup.sh && echo "syntaxe OK"
```

Expected: `shellcheck OK` puis `syntaxe OK`

- [ ] **Step 3 : Committer**

```bash
git add scripts/backup.sh
git commit -m "feat(M5): backup.sh — tar /data | age encrypt (§G-36 chiffrement obligatoire)"
```

---

## Task 5 : `scripts/restore.sh`

**Files:**
- Create: `scripts/restore.sh`

> §G-35 : `restore.sh` restaure config/CA/clés — PAS les workspaces (ils vivent dans les daemons).
> L'avertissement doit être **EXPLICITE et visible** avant toute action.

- [ ] **Step 1 : Créer scripts/restore.sh**

```bash
#!/usr/bin/env bash
# restore.sh — Restaure /data depuis un backup chiffré age (§G-35, §G-36)
#
# §G-35 : AVERTISSEMENT — Ce restore restaure uniquement :
#   ✓ La CA et les clés de confiance (mTLS)
#   ✓ La configuration (config.yaml, .env)
#   ✓ Les clés SSH git
#   ✓ L'état DevPod local (DEVPOD_HOME)
#   ✗ Les workspaces actifs (ils vivent dans les daemons Docker des nœuds)
#   Après restore : les workspaces doivent être re-provisionnés via devpod up.
#
# Usage :
#   AGE_IDENTITY=/root/age-backup.key bash scripts/restore.sh /backup/portal-backup-xxx.tar.gz.age
#
# Variables d'environnement :
#   DATA_ROOT       Racine de destination (défaut : /data)
#   AGE_IDENTITY    Fichier clé privée age (OBLIGATOIRE)
set -euo pipefail

DATA_ROOT="${DATA_ROOT:-/data}"
ARCHIVE="${1:-}"

if [[ -z "$ARCHIVE" ]]; then
    echo "Usage : $0 <archive.tar.gz.age>" >&2
    exit 1
fi

if [[ ! -f "$ARCHIVE" ]]; then
    echo "ERREUR : archive introuvable : $ARCHIVE" >&2
    exit 1
fi

if [[ -z "${AGE_IDENTITY:-}" ]]; then
    echo "ERREUR : AGE_IDENTITY non défini (chemin vers la clé privée age)." >&2
    exit 1
fi

for cmd in age tar; do
    command -v "$cmd" &>/dev/null || { echo "ERREUR : $cmd introuvable" >&2; exit 1; }
done

# ── Avertissement OBLIGATOIRE (§G-35) ────────────────────────────────────────
cat <<'WARNING'

╔══════════════════════════════════════════════════════════════════════════════╗
║  ⚠  AVERTISSEMENT RESTORE — LISEZ AVANT DE CONTINUER  ⚠                   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Ce script restaure : CA, clés, config.yaml, .env, état DevPod.            ║
║                                                                             ║
║  CE QUI N'EST PAS RESTAURÉ :                                                ║
║  • Les workspaces actifs (ils vivent dans les daemons Docker des nœuds).   ║
║  • Les sessions de travail en cours.                                        ║
║  • Les images Docker buildées sur les nœuds.                               ║
║                                                                             ║
║  APRÈS RESTORE :                                                            ║
║  1. Vérifier que tous les nœuds sont encore enrôlés et accessibles.        ║
║  2. Pour chaque user : relancer ses workspaces via le portail (devpod up). ║
║  3. Les données non sauvegardées dans /data sont perdues.                  ║
║                                                                             ║
║  « backup facile » ≠ « reprise transparente des sessions » (§G-35)         ║
╚══════════════════════════════════════════════════════════════════════════════╝

WARNING

if [[ -t 0 ]]; then
    read -rp "Continuer le restore ? [oui/NON] : " CONFIRM
    if [[ "$CONFIRM" != "oui" ]]; then
        echo "Restore annulé."
        exit 0
    fi
else
    echo "(Mode non interactif — restore forcé sans confirmation)"
fi

# ── Sauvegarde de l'existant avant restore ────────────────────────────────────
if [[ -d "$DATA_ROOT" ]]; then
    PRE_RESTORE_BACKUP="$(dirname "$DATA_ROOT")/data-pre-restore-$(date -u +%Y%m%d-%H%M%S)"
    echo "==> Sauvegarde de $DATA_ROOT → $PRE_RESTORE_BACKUP (sécurité)"
    cp -a "$DATA_ROOT" "$PRE_RESTORE_BACKUP"
fi

# ── Restore ──────────────────────────────────────────────────────────────────
echo "==> Déchiffrement et restauration depuis $ARCHIVE..."
PARENT_DIR="$(dirname "$DATA_ROOT")"
age -d -i "$AGE_IDENTITY" "$ARCHIVE" \
    | tar xzf - -C "$PARENT_DIR"

echo ""
echo "==> Restore terminé."
echo ""
echo "Étapes post-restore obligatoires :"
echo "  1. Vérifier que /data/.env est complet (OIDC_CLIENT_SECRET, CF_API_TOKEN, etc.)"
echo "  2. chmod 600 $DATA_ROOT/.env $DATA_ROOT/certs/ca/ca-key.pem"
echo "  3. Redémarrer le portail : docker compose -f deploy/docker-compose.yml up -d"
echo "  4. Vérifier la connectivité aux nœuds enrôlés."
echo "  5. Demander aux utilisateurs de re-lancer leurs workspaces."
echo ""
echo "En cas de problème, la sauvegarde pré-restore est dans :"
echo "  $PRE_RESTORE_BACKUP"
```

- [ ] **Step 2 : Rendre exécutable et passer shellcheck**

```bash
chmod +x scripts/restore.sh
shellcheck scripts/restore.sh && echo "shellcheck OK"
bash -n scripts/restore.sh && echo "syntaxe OK"
```

Expected: `shellcheck OK` puis `syntaxe OK`

- [ ] **Step 3 : Vérifier que l'avertissement §G-35 est présent et lisible**

```bash
grep -c "G-35\|backup facile\|re-lancer\|AVERTISSEMENT" scripts/restore.sh
```

Expected: >= 3

- [ ] **Step 4 : Committer**

```bash
git add scripts/restore.sh
git commit -m "feat(M5): restore.sh — déchiffrement age + avertissement workspaces §G-35"
```

---

## Tests de validation M5

Ces tests vérifient la cohérence de l'ensemble (pas de new pytest — M5 est infrastructure).

- [ ] **Lint global des scripts bash**

```bash
shellcheck scripts/install.sh scripts/backup.sh scripts/restore.sh && echo "Tous shellcheck OK"
```

- [ ] **Syntaxe bash**

```bash
for f in scripts/install.sh scripts/backup.sh scripts/restore.sh; do
    bash -n "$f" && echo "$f : OK"
done
```

- [ ] **Aucun secret dans Dockerfile (§D-21)**

```bash
grep -n "SECRET\|KEY\|TOKEN\|PASSWORD\|CERT" deploy/Dockerfile
```

Expected: `0 lignes` (les variables d'env à secret ne doivent pas apparaître dans le Dockerfile).

- [ ] **Aucune valeur réelle dans .env.example**

```bash
python3 -c "
import re, sys
with open('deploy/.env.example') as f:
    content = f.read()
# Lignes non vides, non commentaires, avec une valeur non vide après =
bad = [l for l in content.splitlines()
       if l.strip() and not l.startswith('#')
       and '=' in l
       and l.split('=', 1)[1].strip() not in ('', 'dev.yoops.org', 'admin@example.com')]
if bad:
    print('ERREUR valeurs trouvées:', bad); sys.exit(1)
else:
    print('OK : .env.example sans valeurs sensibles')
"
```

- [ ] **Tests Python existants non régressés**

```bash
cd backend && uv run pytest -v -q 2>&1 | tail -3
```

Expected: `151 passed` (ou plus si des tests ont été ajoutés).

- [ ] **Commit final de validation**

```bash
git add -A
git status  # Vérifier qu'il ne reste rien d'involontaire
git commit -m "test(M5): validation lint + checks secrets Dockerfile/.env.example"
```

---

## Self-Review

### 1. Couverture spec M5

| Exigence spec | Tâche |
|---|---|
| M5.1 Dockerfile Python 3.12-slim + DevPod pinné | Task 0 |
| M5.1 Docker CLI seul, openssl | Task 0 |
| M5.1 Aucun secret dans l'image (§D-21) | Task 0 + test validation |
| M5.2 CA générée si absente, JAMAIS écrasée (§E-25) | Task 3 |
| M5.2 ca-key.pem perms 600 (§E-26) | Task 3 |
| M5.2 Cert client portail (ca.pem + cert.pem + key.pem) | Task 3 |
| M5.2 config.yaml initial si absent | Task 3 |
| M5.2 /data/.env perms 600, SESSION_SECRET_KEY aléatoire | Task 3 |
| M5.2 docker compose up -d (documenté, pas automatique) | Task 3 |
| M5.3 docker-compose.yml portal + caddy, /data monté | Task 2 |
| M5.3 Réseau interne, Caddy exposé | Task 2 |
| M5.4 Caddyfile racine → portail | Task 2 |
| M5.4 Wildcard *.domain → stub 404 fail-closed (§F-33) | Task 2 |
| M5.4 DNS-01 Cloudflare pour wildcard (§F-30) | Task 1 + Task 2 |
| M5.5 backup.sh chiffré age (§G-36) | Task 4 |
| M5.5 restore.sh + avertissement workspaces (§G-35) | Task 5 |
| .env.example sans valeurs réelles | Task 2 |

### 2. Pièges cochés

- [x] §E-25 : test d'idempotence CA dans Task 3 Step 4
- [x] §E-26 : perms 600 vérifiées dans Task 3 Step 5
- [x] §D-21 : grep sur Dockerfile dans tests validation
- [x] §F-30 : Dockerfile.caddy avec xcaddy + caddy-dns/cloudflare
- [x] §F-33 : Caddyfile wildcard → 404 (stub fail-closed explicitement commenté)
- [x] §G-35 : avertissement complet dans restore.sh + vérification grep
- [x] §G-36 : AGE_RECIPIENT obligatoire dans backup.sh, refus explicite si absent
- [x] §G-37 : mentionné dans backup.sh (atomic writes + note sur quiesce)

### 3. Cohérence des types/chemins

- `DATA_ROOT` utilisé partout de façon cohérente dans les 3 scripts
- `DOCKER_CERT_PATH` pointera vers `/data/certs/portal` — `ca.pem`, `cert.pem`, `key.pem` générés avec ces noms exacts (convention Docker)
- `$BASE_DOMAIN` dans Caddyfile = variable d'env issue de `/data/.env` → cohérent avec `.env.example`
- `AGE_RECIPIENT` (clé publique, backup) / `AGE_IDENTITY` (clé privée, restore) — convention age standard
