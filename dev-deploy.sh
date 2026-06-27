#!/usr/bin/env bash
# Déploiement dev — portal exposé directement sur :80, sans Caddy.
# Initialise /data/.env depuis deploy/.env.example si absent,
# génère SESSION_SECRET_KEY + LOCAL_PASSWORD + LOCAL_PASSWORD_HASH automatiquement.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERREUR : ce script doit être exécuté en root (sudo ./dev-deploy.sh)." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_ROOT="${DATA_ROOT:-/data}"
ENV_FILE="${DATA_ROOT}/.env"

# ─── Initialisation du .env si absent ────────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
    echo "==> .env absent — initialisation depuis deploy/.env.example..."

    command -v python3 &>/dev/null || apt-get install -y --no-install-recommends python3 >/dev/null 2>&1
    python3 -c "import bcrypt" 2>/dev/null || apt-get install -y --no-install-recommends python3-bcrypt >/dev/null 2>&1

    mkdir -p "$DATA_ROOT"
    cp "${SCRIPT_DIR}/deploy/.env.example" "$ENV_FILE"
    chmod 600 "$ENV_FILE"

    SESSION_KEY="$(openssl rand -hex 32)"
    LOCAL_PASS="$(openssl rand -hex 12)"
    LOCAL_HASH="$(PASS="$LOCAL_PASS" python3 -c \
        "import bcrypt, os; print(bcrypt.hashpw(os.environ['PASS'].encode(), bcrypt.gensalt()).decode())")"
    # docker-compose interprole $VAR dans env_file : échapper $ → $$ pour que le
    # conteneur reçoive le hash bcrypt intact ($2b$12$… → $$2b$$12$$…).
    LOCAL_HASH_ESCAPED="$(printf '%s' "$LOCAL_HASH" | sed 's/\$/\$\$/g')"

    sed -i "s|^SESSION_SECRET_KEY=.*|SESSION_SECRET_KEY=${SESSION_KEY}|" "$ENV_FILE"
    sed -i "s|^LOCAL_PASSWORD=.*|LOCAL_PASSWORD=${LOCAL_PASS}|" "$ENV_FILE"
    sed -i "s|^LOCAL_PASSWORD_HASH=.*|LOCAL_PASSWORD_HASH=${LOCAL_HASH_ESCAPED}|" "$ENV_FILE"

    VAULT_KEK="$(openssl rand -hex 32)"
    sed -i "s|^PORTAL_VAULT_KEK=.*|PORTAL_VAULT_KEK=${VAULT_KEK}|" "$ENV_FILE"

    echo "    .env créé — credentials locaux et PORTAL_VAULT_KEK générés."
fi

# ─── Génération PORTAL_VAULT_KEK si absent ou vide ───────────────────────────
if ! grep -qE '^PORTAL_VAULT_KEK=.+' "$ENV_FILE"; then
    echo "==> PORTAL_VAULT_KEK manquant ou vide — génération..."
    VAULT_KEK="$(openssl rand -hex 32)"
    if grep -q '^PORTAL_VAULT_KEK=' "$ENV_FILE"; then
        sed -i "s|^PORTAL_VAULT_KEK=.*|PORTAL_VAULT_KEK=${VAULT_KEK}|" "$ENV_FILE"
    else
        echo "PORTAL_VAULT_KEK=${VAULT_KEK}" >> "$ENV_FILE"
    fi
    echo "    PORTAL_VAULT_KEK généré et ajouté au .env."
fi

# ─── Déploiement ──────────────────────────────────────────────────────────────
exec env COMPOSE_FILE=deploy/docker-compose.dev.yml \
    DATA_ROOT="$DATA_ROOT" \
    "${SCRIPT_DIR}/scripts/deploy-portal.sh" "$@"
