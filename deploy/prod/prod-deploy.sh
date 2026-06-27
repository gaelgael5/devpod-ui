#!/usr/bin/env bash
# prod-deploy.sh — Déploiement / mise à jour du portail workspace en PRODUCTION.
# À exécuter directement sur la VM prod en root :
#   cd /opt/workspace-portal && ./deploy/prod/prod-deploy.sh main
# Suppose une VM provisionnée via scripts/proxmox-clone-vm-node.sh (docker + git + python3).
# Idempotent : peut être relancé sans danger (aucun secret déjà présent n'est réécrit).
#
# Usage :
#   ./deploy/prod/prod-deploy.sh [BRANCH]
#   ex : ./deploy/prod/prod-deploy.sh main

set -euo pipefail
IFS=$'\n\t'

APP_DIR="${APP_DIR:-/opt/workspace-portal}"
COMPOSE_FILE="deploy/prod/docker-compose.prod.yml"
ENV_EXAMPLE="deploy/prod/.env.prod.example"
ENV_FILE="${ENV_FILE:-/data/.env}"

# ─── Argument : branche cible (défaut main) ──────────────────────────────────
TARGET_BRANCH=""
for arg in "$@"; do
    case "$arg" in
        --*) echo "ERREUR : flag inconnu : $arg" >&2; exit 1 ;;
        *)
            if [[ -n "$TARGET_BRANCH" ]]; then
                echo "ERREUR : plusieurs branches passées en argument." >&2; exit 1
            fi
            TARGET_BRANCH="$arg"
            ;;
    esac
done

if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERREUR : ce script doit être exécuté en root." >&2
    exit 1
fi

# ─── Prérequis ────────────────────────────────────────────────────────────────
for cmd in docker git openssl python3; do
    command -v "$cmd" &>/dev/null || {
        echo "ERREUR : '$cmd' introuvable." >&2; exit 1
    }
done
docker compose version &>/dev/null || {
    echo "ERREUR : docker compose v2 manquant (apt-get install -y docker-compose-plugin)." >&2
    exit 1
}

cd "$APP_DIR"

# ─── Auto-mise à jour : git pull d'abord, puis ré-exécution si le script a changé ──
echo "==> Mise à jour du dépôt..."
git fetch origin
if [[ -n "$TARGET_BRANCH" ]]; then
    git checkout "$TARGET_BRANCH"
fi
CURRENT="$(git branch --show-current)"
BEFORE="$(git rev-parse HEAD)"
git pull --ff-only origin "$CURRENT"
AFTER="$(git rev-parse HEAD)"

if [[ "$BEFORE" != "$AFTER" ]]; then
    echo "    Dépôt mis à jour — ré-exécution du script..."
    exec "$0" "$@"
fi

# ─── Fonctions utilitaires .env ───────────────────────────────────────────────

# Lit la valeur d'une clé dans $ENV_FILE (retourne "" si absente ou vide).
# tr -d '\r' protège contre les fins de ligne CRLF (copie depuis Windows).
_get_env() {
    local key="$1"
    grep -m1 "^${key}=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- | tr -d '\r' || true
}

# Écrit (ou remplace) une clé=valeur dans $ENV_FILE.
_set_env() {
    local key="$1" value="$2"
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
    else
        echo "${key}=${value}" >> "$ENV_FILE"
    fi
}

# ─── 0) Initialisation du fichier .env ────────────────────────────────────────
echo ""
echo "==> [0/4] Vérification de ${ENV_FILE}..."

if [[ ! -f "$ENV_FILE" ]]; then
    echo "    ${ENV_FILE} absent — copie depuis ${ENV_EXAMPLE}"
    install -m 600 "$ENV_EXAMPLE" "$ENV_FILE"
fi

# Normaliser les fins de ligne CRLF → LF (fichier potentiellement édité sur Windows)
if grep -qP '\r' "$ENV_FILE" 2>/dev/null; then
    sed -i 's/\r$//' "$ENV_FILE"
    echo "    Fins de ligne CRLF converties en LF"
fi

# POSTGRES_USER
if [[ -z "$(_get_env POSTGRES_USER)" ]]; then
    _set_env POSTGRES_USER "portal_$(openssl rand -hex 4)"
    echo "    POSTGRES_USER généré"
fi

# POSTGRES_PASSWORD
if [[ -z "$(_get_env POSTGRES_PASSWORD)" ]]; then
    _set_env POSTGRES_PASSWORD "$(openssl rand -hex 24)"
    echo "    POSTGRES_PASSWORD généré"
fi

# DATABASE_URL (hostname = service Docker `postgres`)
if [[ -z "$(_get_env DATABASE_URL)" ]]; then
    _set_env DATABASE_URL \
        "postgresql+asyncpg://$(_get_env POSTGRES_USER):$(_get_env POSTGRES_PASSWORD)@postgres/portal"
    echo "    DATABASE_URL construit"
fi

# SESSION_SECRET_KEY
if [[ -z "$(_get_env SESSION_SECRET_KEY)" ]]; then
    _set_env SESSION_SECRET_KEY "$(openssl rand -hex 32)"
    echo "    SESSION_SECRET_KEY généré"
fi

# PORTAL_VAULT_KEK — généré UNE SEULE FOIS, jamais réécrit (sinon vault illisible).
if [[ -z "$(_get_env PORTAL_VAULT_KEK)" ]]; then
    _set_env PORTAL_VAULT_KEK "$(openssl rand -hex 32)"
    echo "    PORTAL_VAULT_KEK généré (clé de chiffrement du vault — conserver le .env)"
fi

# LOCAL_USER (défaut admin)
if [[ -z "$(_get_env LOCAL_USER)" ]]; then
    _set_env LOCAL_USER "admin"
fi

# LOCAL_PASSWORD + LOCAL_PASSWORD_HASH (bcrypt). Hash recalculé si absent.
if [[ -z "$(_get_env LOCAL_PASSWORD_HASH)" ]]; then
    LOCAL_PASS="$(_get_env LOCAL_PASSWORD)"
    if [[ -z "$LOCAL_PASS" ]]; then
        LOCAL_PASS="$(openssl rand -hex 12)"
        _set_env LOCAL_PASSWORD "$LOCAL_PASS"
    fi
    python3 -c "import bcrypt" 2>/dev/null || {
        echo "    Installation de python3-bcrypt..."
        apt-get install -y --no-install-recommends python3-bcrypt >/dev/null 2>&1
    }
    LOCAL_HASH="$(printf '%s' "$LOCAL_PASS" | python3 -c "
import sys, bcrypt
p = sys.stdin.read().strip().encode()
print(bcrypt.hashpw(p, bcrypt.gensalt()).decode())
")"
    _set_env LOCAL_PASSWORD_HASH "$LOCAL_HASH"
    echo "    LOCAL_PASSWORD / LOCAL_PASSWORD_HASH générés"
fi

# Validation : échouer si une variable auto-générable critique est encore vide.
for _required_key in POSTGRES_USER POSTGRES_PASSWORD DATABASE_URL SESSION_SECRET_KEY PORTAL_VAULT_KEK; do
    if [[ -z "$(_get_env "$_required_key")" ]]; then
        echo "ERREUR : ${_required_key} vide dans ${ENV_FILE} après génération." >&2
        exit 1
    fi
done

# Charger le .env dans l'environnement shell : docker compose résout ${VAR} depuis l'env
# en priorité sur --env-file.
set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

# ─── 1) Build ─────────────────────────────────────────────────────────────────
echo ""
echo "==> [1/4] Build des images (portal + caddy)..."
docker compose -f "$COMPOSE_FILE" build

# ─── 2) Redémarrage de la stack ──────────────────────────────────────────────
echo ""
echo "==> [2/4] Redémarrage de la stack..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" down --remove-orphans || true
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --remove-orphans
echo ""
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps

# ─── 3) Migrations Alembic ────────────────────────────────────────────────────
echo ""
echo "==> [3/4] Migrations Alembic..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" \
    exec -T portal uv run alembic upgrade head

# ─── 4) Smoke — healthcheck du conteneur portal (timeout 90s) ─────────────────
# Aucun port portal n'est publié en prod : on lit l'état du healthcheck Docker.
echo ""
echo "==> [4/4] Smoke /health (timeout 90s)..."
SMOKE_OK=0
ELAPSED=0
PORTAL_ID="$(docker compose -f "$COMPOSE_FILE" ps -q portal 2>/dev/null)"
while [[ $ELAPSED -lt 90 ]]; do
    STATUS="$(docker inspect --format='{{.State.Health.Status}}' "$PORTAL_ID" 2>/dev/null || echo '?')"
    if [[ "$STATUS" == "healthy" ]]; then
        SMOKE_OK=1; break
    fi
    sleep 5
    ELAPSED=$(( ELAPSED + 5 ))
done

if [[ $SMOKE_OK -ne 1 ]]; then
    echo "" >&2
    echo "  ✗ Le conteneur portal n'est pas 'healthy' après 90s." >&2
    echo "  Vérifier : docker compose -f ${COMPOSE_FILE} logs --tail=80 portal" >&2
    exit 1
fi

# ─── Récapitulatif (affiché UNE seule fois — noter les credentials maintenant) ──
_BASE_DOMAIN="$(_get_env BASE_DOMAIN)"
_LOCAL_USER="$(_get_env LOCAL_USER)"
_LOCAL_PASS="$(_get_env LOCAL_PASSWORD)"
echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "  ✓ Portail PROD opérationnel"
echo ""
echo "  Accès  : https://${_BASE_DOMAIN}"
echo "  Login  : ${_LOCAL_USER} / ${_LOCAL_PASS}"
echo "  Env    : ${ENV_FILE}  (sauvegarder — contient PORTAL_VAULT_KEK)"
echo ""

# Avertissements (pas de fail-closed : on génère, on prévient une fois).
if [[ -z "$(_get_env CF_API_TOKEN)" ]]; then
    echo "  ⚠ CF_API_TOKEN vide → TLS DNS-01 inactif, HTTPS indisponible."
    echo "    Renseigner CF_API_TOKEN dans ${ENV_FILE} puis relancer ce script."
fi
if [[ -z "$(_get_env OIDC_CLIENT_SECRET)" ]]; then
    echo "  ⚠ OIDC_CLIENT_SECRET vide → connexion OIDC désactivée (auth locale seule)."
fi
echo ""
echo "  Logs   : docker compose -f ${COMPOSE_FILE} logs -f"
echo "══════════════════════════════════════════════════════════════════"
