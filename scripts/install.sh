#!/usr/bin/env bash
# install.sh — Initialise /data et prépare le démarrage du portail workspace
# Idempotent : peut être ré-exécuté sans danger.
# §E-25 : la CA n'est JAMAIS régénérée si /data/certs/ca/ca.pem existe déjà.
# Usage : sudo bash scripts/install.sh [--data-root /data] [--compose-file deploy/docker-compose.yml]
set -euo pipefail
umask 077  # Fichiers créés en 600, répertoires en 700 par défaut

# ── Paramètres par défaut ────────────────────────────────────────────────────
DATA_ROOT="${PORTAL_DATA_ROOT:-/data}"
COMPOSE_FILE="${PORTAL_COMPOSE_FILE:-$(dirname "$0")/../deploy/docker-compose.yml}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --data-root)    DATA_ROOT="$2";    shift 2 ;;
        --compose-file) COMPOSE_FILE="$2"; shift 2 ;;
        *) echo "Argument inconnu : $1" >&2; exit 1 ;;
    esac
done

CA_DIR="$DATA_ROOT/certs/ca"
PORTAL_CERT_DIR="$DATA_ROOT/certs/portal"

# ── Outils requis ────────────────────────────────────────────────────────────
echo "==> Vérification des outils requis..."
for cmd in openssl docker python3; do
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
    "$DATA_ROOT/certs/nodes" \
    "$DATA_ROOT/.devpod"
chmod 700 "$DATA_ROOT"
chmod 700 "$DATA_ROOT/certs" "$DATA_ROOT/certs/ca" "$DATA_ROOT/certs/portal" "$DATA_ROOT/certs/nodes"
chmod 700 "$DATA_ROOT/.devpod"

# ── 2. CA — §E-25 : NE JAMAIS régénérer si déjà présente ───────────────────
if [[ -f "$CA_DIR/ca.pem" ]]; then
    echo "==> CA déjà présente — skip (§E-25). Empreinte :"
    openssl x509 -in "$CA_DIR/ca.pem" -noout -fingerprint -sha256
else
    echo "==> Génération de la CA (racine de confiance mTLS)..."
    openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-384 \
        -out "$CA_DIR/ca-key.pem" 2>/dev/null
    chmod 600 "$CA_DIR/ca-key.pem"
    openssl req -new -x509 \
        -key "$CA_DIR/ca-key.pem" \
        -sha384 \
        -days 3650 \
        -subj "/CN=workspace-portal-ca/O=workspace-portal" \
        -out "$CA_DIR/ca.pem"
    echo "    CA générée. Empreinte :"
    openssl x509 -in "$CA_DIR/ca.pem" -noout -fingerprint -sha256
fi

# ── 3. Cert client portail ───────────────────────────────────────────────────
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

    # Credentials auth locale — bcrypt via python3
    python3 -c "import bcrypt" 2>/dev/null || {
        echo "    Installation de python3-bcrypt..."
        apt-get install -y --no-install-recommends python3-bcrypt >/dev/null 2>&1
    }
    LOCAL_PASS=$(openssl rand -hex 12)
    LOCAL_HASH=$(echo "$LOCAL_PASS" | python3 -c "
import sys, bcrypt
p = sys.stdin.read().strip().encode()
print(bcrypt.hashpw(p, bcrypt.gensalt()).decode())
")

    cat > "$ENV_FILE" <<ENVEOF
# Généré par install.sh
# Perms 600 requises — ne JAMAIS commiter ce fichier (§D-21)

SESSION_SECRET_KEY=${SESSION_KEY}
OIDC_CLIENT_SECRET=
HARPOCRATE_API_KEY=
CFM_API_KEY=
CF_API_TOKEN=
ACME_EMAIL=
BASE_DOMAIN=${BASE_DOMAIN:-dev.yoops.org}

# Auth locale (fallback sans OIDC)
LOCAL_USER=admin
LOCAL_PASSWORD=${LOCAL_PASS}
LOCAL_PASSWORD_HASH=${LOCAL_HASH}
ENVEOF
    chmod 600 "$ENV_FILE"
    echo "    .env créé."
    echo ""
    echo "    ┌─────────────────────────────────────────────┐"
    echo "    │  Credentials locaux (noter maintenant)      │"
    echo "    │  Login    : admin                           │"
    echo "    │  Password : ${LOCAL_PASS}  │"
    echo "    └─────────────────────────────────────────────┘"
fi

# ── 6. Instructions de démarrage ─────────────────────────────────────────────
echo ""
echo "==> Structure /data initialisée. Pour démarrer le portail :"
echo "    1. Vérifier/compléter $ENV_FILE"
echo "    2. docker compose -f $COMPOSE_FILE up -d"
echo ""
echo "Empreinte CA (à noter pour vérification lors de l'enrôlement des nœuds) :"
openssl x509 -in "$CA_DIR/ca.pem" -noout -fingerprint -sha256
