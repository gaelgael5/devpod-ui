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

# ─── Auto-mise à jour du repo avant de déléguer ──────────────────────────────
# Garantit que deploy-portal.sh sur disque est bien la version courante.
if [[ -d "${SCRIPT_DIR}/.git" ]]; then
    _CURRENT_BRANCH="$(git -C "$SCRIPT_DIR" branch --show-current 2>/dev/null || true)"
    if [[ -n "$_CURRENT_BRANCH" ]]; then
        git -C "$SCRIPT_DIR" pull --ff-only origin "$_CURRENT_BRANCH" 2>/dev/null || true
    fi
    unset _CURRENT_BRANCH
fi

# ─── Création du .env si absent ──────────────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
    echo "==> .env absent — initialisation depuis deploy/.env.example..."
    mkdir -p "$DATA_ROOT"
    cp "${SCRIPT_DIR}/deploy/.env.example" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
fi

# ─── Complétion des valeurs manquantes ou vides ──────────────────────────────
# Chaque clé est vérifiée individuellement : le .env peut exister mais avoir
# des valeurs vides (ex. après --resetdb ou copie depuis .env.example).

_env_get() { grep -m1 "^${1}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '\r' || true; }
_env_set() {
    local key="$1" val="$2"
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
    else
        echo "${key}=${val}" >> "$ENV_FILE"
    fi
}

if [[ -z "$(_env_get POSTGRES_USER)" ]]; then
    PG_USER="portal_$(openssl rand -hex 4)"
    PG_PASS="$(openssl rand -hex 24)"
    DB_URL="postgresql+asyncpg://${PG_USER}:${PG_PASS}@postgres/portal"
    _env_set POSTGRES_USER     "$PG_USER"
    _env_set POSTGRES_PASSWORD "$PG_PASS"
    _env_set DATABASE_URL      "$DB_URL"
    echo "==> POSTGRES_USER généré : ${PG_USER}"
fi

if [[ -z "$(_env_get SESSION_SECRET_KEY)" ]]; then
    _env_set SESSION_SECRET_KEY "$(openssl rand -hex 32)"
    echo "==> SESSION_SECRET_KEY généré"
fi

if [[ -z "$(_env_get LOCAL_PASSWORD)" ]]; then
    command -v python3 &>/dev/null || apt-get install -y --no-install-recommends python3 >/dev/null 2>&1
    python3 -c "import bcrypt" 2>/dev/null || apt-get install -y --no-install-recommends python3-bcrypt >/dev/null 2>&1
    LOCAL_PASS="$(openssl rand -hex 12)"
    LOCAL_HASH="$(PASS="$LOCAL_PASS" python3 -c \
        "import bcrypt, os; print(bcrypt.hashpw(os.environ['PASS'].encode(), bcrypt.gensalt()).decode())")"
    LOCAL_HASH_ESCAPED="$(printf '%s' "$LOCAL_HASH" | sed 's/\$/\$\$/g')"
    _env_set LOCAL_PASSWORD      "$LOCAL_PASS"
    _env_set LOCAL_PASSWORD_HASH "$LOCAL_HASH_ESCAPED"
    echo "==> LOCAL_PASSWORD généré : ${LOCAL_PASS}"
fi

if [[ -z "$(_env_get PORTAL_VAULT_KEK)" ]]; then
    _env_set PORTAL_VAULT_KEK "$(openssl rand -hex 32)"
    echo "==> PORTAL_VAULT_KEK généré"
fi

unset -f _env_get _env_set

# ─── Déploiement ──────────────────────────────────────────────────────────────
exec env COMPOSE_FILE=deploy/docker-compose.dev.yml \
    DATA_ROOT="$DATA_ROOT" \
    APP_DIR="$SCRIPT_DIR" \
    "${SCRIPT_DIR}/scripts/deploy-portal.sh" "$@"
