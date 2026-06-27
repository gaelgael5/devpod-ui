#!/usr/bin/env bash
# prod-deploy.sh — Bootstrap de livraison PRODUCTION du portail workspace.
#
# Conçu pour être lancé directement par :
#   curl -sSL https://raw.githubusercontent.com/gaelgael5/devpod-ui/refs/heads/main/deploy/prod/prod-deploy.sh | bash -s --
#
# Ne fait AUCUN git clone et ne récupère AUCUN code source. Il :
#   1. crée /opt/workspace-portal et y télécharge les fichiers de conf nécessaires,
#   2. initialise /data (CA, certs, config.yaml, .env) via install.sh,
#   3. complète /data/.env avec les variables prod (postgres, vault, dev_mode),
#   4. tire les images publiées sur GHCR (branche main) et démarre la stack,
#   5. applique les migrations Alembic et vérifie la santé du portail.
# Idempotent : un nouveau lancement = mise à jour vers la dernière image main.

set -euo pipefail
IFS=$'\n\t'

# ─── Configuration ────────────────────────────────────────────────────────────
REF="${REF:-main}"                       # branche source de la conf + tag image
OWNER="gaelgael5"
REPO="devpod-ui"
RAW_BASE="https://raw.githubusercontent.com/${OWNER}/${REPO}/refs/heads/${REF}"
APP_DIR="${APP_DIR:-/opt/workspace-portal}"
DATA_ROOT="${DATA_ROOT:-/data}"
ENV_FILE="${DATA_ROOT}/.env"
COMPOSE_FILE="${APP_DIR}/docker-compose.prod.yml"
BASE_DOMAIN="${BASE_DOMAIN:-pod.yoops.org}"

# ─── Prérequis ────────────────────────────────────────────────────────────────
if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERREUR : ce script doit être exécuté en root." >&2
    exit 1
fi
for cmd in docker curl openssl python3; do
    command -v "$cmd" &>/dev/null || {
        echo "ERREUR : '$cmd' introuvable." >&2; exit 1
    }
done
docker compose version &>/dev/null || {
    echo "ERREUR : docker compose v2 manquant (apt-get install -y docker-compose-plugin)." >&2
    exit 1
}

# ─── 1) Répertoire + téléchargement de la conf ───────────────────────────────
echo "==> [1/5] Préparation de ${APP_DIR} (téléchargement conf, ref=${REF})..."
mkdir -p "$APP_DIR"

_dl() {  # _dl <chemin_dans_repo> <destination>
    local src="$1" dest="$2"
    curl -fsSL "${RAW_BASE}/${src}" -o "$dest" || {
        echo "ERREUR : téléchargement échoué : ${RAW_BASE}/${src}" >&2; exit 1
    }
    echo "    ${dest}"
}
_dl deploy/prod/docker-compose.prod.yml "$COMPOSE_FILE"
_dl deploy/prod/Caddyfile.prod          "${APP_DIR}/Caddyfile.prod"
_dl scripts/install.sh                  "${APP_DIR}/install.sh"

# ─── 2) Initialisation de /data (CA, certs, config.yaml, .env de base) ───────
echo ""
echo "==> [2/5] Initialisation de ${DATA_ROOT} (install.sh, idempotent)..."
env PORTAL_BASE_DOMAIN="$BASE_DOMAIN" \
    PORTAL_EXTERNAL_URL="https://${BASE_DOMAIN}" \
    bash "${APP_DIR}/install.sh" \
        --data-root    "$DATA_ROOT" \
        --compose-file "$COMPOSE_FILE"

# ─── Fonctions utilitaires .env ───────────────────────────────────────────────
_get_env() {
    grep -m1 "^$1=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- | tr -d '\r' || true
}
_set_env() {
    if grep -q "^$1=" "$ENV_FILE" 2>/dev/null; then
        sed -i "s|^$1=.*|$1=$2|" "$ENV_FILE"
    else
        echo "$1=$2" >> "$ENV_FILE"
    fi
}

# ─── 3) Complément de /data/.env (clés prod absentes d'install.sh) ───────────
# Idempotent : aucune valeur déjà présente n'est réécrite.
echo ""
echo "==> [3/5] Complément de ${ENV_FILE}..."

if [[ -z "$(_get_env POSTGRES_USER)" ]]; then
    _set_env POSTGRES_USER "portal_$(openssl rand -hex 4)"
    echo "    POSTGRES_USER généré"
fi
if [[ -z "$(_get_env POSTGRES_PASSWORD)" ]]; then
    _set_env POSTGRES_PASSWORD "$(openssl rand -hex 24)"
    echo "    POSTGRES_PASSWORD généré"
fi
if [[ -z "$(_get_env DATABASE_URL)" ]]; then
    _set_env DATABASE_URL \
        "postgresql+asyncpg://$(_get_env POSTGRES_USER):$(_get_env POSTGRES_PASSWORD)@postgres/portal"
    echo "    DATABASE_URL construit"
fi
# PORTAL_VAULT_KEK — généré UNE SEULE FOIS, jamais réécrit (sinon vault illisible).
if [[ -z "$(_get_env PORTAL_VAULT_KEK)" ]]; then
    _set_env PORTAL_VAULT_KEK "$(openssl rand -hex 32)"
    echo "    PORTAL_VAULT_KEK généré (conserver le .env)"
fi
if [[ -z "$(_get_env DEV_MODE)" ]]; then
    _set_env DEV_MODE "false"
fi
chmod 600 "$ENV_FILE"

# ─── 4) Pull des images GHCR + démarrage ─────────────────────────────────────
echo ""
echo "==> [4/5] Pull des images (GHCR, tag main) + démarrage de la stack..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" pull
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --remove-orphans
echo ""
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps

echo ""
echo "==> Migrations Alembic..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" \
    exec -T portal uv run alembic upgrade head

# ─── 5) Smoke — healthcheck du conteneur portal (timeout 90s) ────────────────
echo ""
echo "==> [5/5] Smoke /health (timeout 90s)..."
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

# ─── Récapitulatif (affiché UNE seule fois — noter les credentials) ──────────
_LOCAL_USER="$(_get_env LOCAL_USER)"
_LOCAL_PASS="$(_get_env LOCAL_PASSWORD)"
echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "  ✓ Portail PROD opérationnel"
echo ""
echo "  Accès  : https://${BASE_DOMAIN}"
echo "  Login  : ${_LOCAL_USER} / ${_LOCAL_PASS}"
echo "  Env    : ${ENV_FILE}  (sauvegarder — contient PORTAL_VAULT_KEK)"
echo ""
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
