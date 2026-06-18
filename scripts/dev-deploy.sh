#!/usr/bin/env bash
# dev-deploy.sh — Redéploiement du portail workspace sur la VM de test.
# À exécuter directement sur la VM en root (cd /opt/workspace-portal && ./scripts/dev-deploy.sh).
# Suppose que /data est déjà initialisé (install.sh déjà passé).
# Idempotent : peut être relancé sans danger.
#
# Usage :
#   ./scripts/dev-deploy.sh [BRANCH]
#   ex : ./scripts/dev-deploy.sh dev

set -euo pipefail
IFS=$'\n\t'

APP_DIR="${APP_DIR:-/opt/workspace-portal}"
COMPOSE_FILE="deploy/docker-compose.dev.yml"
ENV_FILE="/data/.env"

# ─── Argument : branche cible ─────────────────────────────────────────────────
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
# tr -d '\r' protège contre les fichiers à fins de ligne CRLF (copie depuis Windows).
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
echo "==> [0/3] Vérification de ${ENV_FILE}..."

if [[ ! -f "$ENV_FILE" ]]; then
    echo "    ${ENV_FILE} absent — copie depuis deploy/.env.example"
    cp deploy/.env.example "$ENV_FILE"
    chmod 600 "$ENV_FILE"
fi

# Normaliser les fins de ligne CRLF → LF (fichier potentiellement édité sur Windows)
if grep -qP '\r' "$ENV_FILE" 2>/dev/null; then
    sed -i 's/\r$//' "$ENV_FILE"
    echo "    Fins de ligne CRLF converties en LF"
fi

# Générer POSTGRES_USER si vide
if [[ -z "$(_get_env POSTGRES_USER)" ]]; then
    PG_USER="portal_$(openssl rand -hex 4)"
    _set_env POSTGRES_USER "$PG_USER"
    echo "    POSTGRES_USER généré : ${PG_USER}"
fi

# Générer POSTGRES_PASSWORD si vide
if [[ -z "$(_get_env POSTGRES_PASSWORD)" ]]; then
    PG_PASS="$(openssl rand -hex 24)"
    _set_env POSTGRES_PASSWORD "$PG_PASS"
    echo "    POSTGRES_PASSWORD généré (64 chars hex)"
fi

# Construire DATABASE_URL si vide (utilise le hostname du service Docker)
if [[ -z "$(_get_env DATABASE_URL)" ]]; then
    PG_USER="$(_get_env POSTGRES_USER)"
    PG_PASS="$(_get_env POSTGRES_PASSWORD)"
    DB_URL="postgresql+asyncpg://${PG_USER}:${PG_PASS}@postgres/portal"
    _set_env DATABASE_URL "$DB_URL"
    echo "    DATABASE_URL construit"
fi

# Générer SESSION_SECRET_KEY si vide
if [[ -z "$(_get_env SESSION_SECRET_KEY)" ]]; then
    _set_env SESSION_SECRET_KEY "$(openssl rand -hex 32)"
    echo "    SESSION_SECRET_KEY généré"
fi

# Validation : échouer explicitement si une variable critique est encore vide
for _required_key in POSTGRES_USER POSTGRES_PASSWORD SESSION_SECRET_KEY; do
    if [[ -z "$(_get_env "$_required_key")" ]]; then
        echo "ERREUR : ${_required_key} vide dans ${ENV_FILE} après génération automatique." >&2
        echo "  → Éditer manuellement ${ENV_FILE} et définir ${_required_key}." >&2
        exit 1
    fi
done

# Charger toutes les variables du .env dans l'environnement shell :
# docker compose résout ${VAR} depuis l'env shell en priorité sur --env-file.
set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

# ─── 1) Build + redémarrage ───────────────────────────────────────────────────
echo ""
echo "==> [1/3] Build de l'image Docker..."
docker compose -f "$COMPOSE_FILE" build

echo ""
echo "==> [2/3] Redémarrage de la stack..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" down --remove-orphans || true
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --remove-orphans

echo ""
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps

# ─── 3) Migrations Alembic ────────────────────────────────────────────────────
echo ""
echo "==> Migrations Alembic..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" \
    exec portal uv run alembic upgrade head

# ─── 4) Smoke /health ─────────────────────────────────────────────────────────
echo ""
echo "==> [3/3] Smoke /health (timeout 60s)..."
SMOKE_OK=0
ELAPSED=0
while [[ $ELAPSED -lt 60 ]]; do
    if curl -sf -m 3 "http://localhost:8080/health" &>/dev/null; then
        SMOKE_OK=1; break
    fi
    sleep 5
    ELAPSED=$(( ELAPSED + 5 ))
done

if [[ $SMOKE_OK -eq 1 ]]; then
    echo ""
    echo "  ✓ Portail opérationnel — http://localhost:8080/health"
else
    echo "" >&2
    echo "  ✗ /health ne répond pas après 60s" >&2
    echo "  Vérifier : docker compose -f ${COMPOSE_FILE} logs --tail=80 portal" >&2
    exit 1
fi

echo ""
echo "==> Logs (80 dernières lignes) :"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" logs --tail=80
