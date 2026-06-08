#!/usr/bin/env bash
# deploy-portal.sh — Déploiement du portail workspace sur une VM de dev/test.
# À exécuter en root dans la VM (directement ou via remote-deploy.ps1).
# Idempotent : peut être relancé sans danger.
#
# Usage :
#   ./scripts/deploy-portal.sh [BRANCH]
#   ex : ./scripts/deploy-portal.sh main
#
# Variables d'env reconnues (toutes optionnelles si /data déjà initialisé) :
#   REPO_URL               URL git du repo   (défaut : HTTPS public gaelgael5/devpod-ui)
#   DATA_ROOT              Racine /data       (défaut : /data)
#   PORTAL_BASE_DOMAIN     Domaine wildcard   (défaut : dev.yoops.org)
#   PORTAL_EXTERNAL_URL    URL externe du portail
#   PORTAL_OIDC_ISSUER     URL issuer Keycloak
#   PORTAL_OIDC_CLIENT_ID  Client ID OIDC
#   OIDC_CLIENT_SECRET     Secret client Keycloak (injecté dans /data/.env)

set -euo pipefail
IFS=$'\n\t'

# ─── Configuration ────────────────────────────────────────────────────────────
REPO_URL="${REPO_URL:-https://github.com/gaelgael5/devpod-ui.git}"
APP_DIR="${APP_DIR:-/opt/workspace-portal}"
DATA_ROOT="${DATA_ROOT:-/data}"
COMPOSE_FILE="deploy/docker-compose.yml"

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

# ─── 0) Prérequis ─────────────────────────────────────────────────────────────
echo "==> Vérification des prérequis..."

if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERREUR : ce script doit être exécuté en root." >&2
    exit 1
fi

for cmd in docker git openssl; do
    command -v "$cmd" &>/dev/null || {
        echo "ERREUR : '$cmd' introuvable." >&2
        echo "  Installer : apt-get install -y docker.io git openssl" >&2
        exit 1
    }
done

if ! docker compose version &>/dev/null; then
    echo "ERREUR : docker compose v2 manquant." >&2
    echo "  Installer : apt-get install -y docker-compose-plugin" >&2
    exit 1
fi

echo "    Prérequis OK."

# ─── 1) Positionnement dans le repo ───────────────────────────────────────────
echo ""
if [[ -d "${APP_DIR}/.git" ]]; then
    if [[ -n "$TARGET_BRANCH" ]]; then
        echo "==> [1/4] Repo présent — switch vers ${TARGET_BRANCH}..."
        git -C "$APP_DIR" fetch origin
        git -C "$APP_DIR" checkout "$TARGET_BRANCH"
        git -C "$APP_DIR" pull --ff-only origin "$TARGET_BRANCH"
    else
        CURRENT="$(git -C "$APP_DIR" branch --show-current)"
        echo "==> [1/4] Repo présent — pull (${CURRENT})..."
        git -C "$APP_DIR" pull --ff-only
    fi
else
    TARGET_BRANCH="${TARGET_BRANCH:-main}"
    echo "==> [1/4] Premier clone (branche ${TARGET_BRANCH})..."
    mkdir -p "$(dirname "$APP_DIR")"
    git clone --branch "$TARGET_BRANCH" "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"

# ─── 2) Initialiser /data (install.sh — idempotent, §E-25) ──────────────────
echo ""
echo "==> [2/4] Initialisation de /data (install.sh)..."

# Construire le préfixe d'env vars pour install.sh non-interactif
INSTALL_VARS=()
[[ -n "${PORTAL_BASE_DOMAIN:-}"    ]] && INSTALL_VARS+=( "PORTAL_BASE_DOMAIN=${PORTAL_BASE_DOMAIN}" )
[[ -n "${PORTAL_EXTERNAL_URL:-}"   ]] && INSTALL_VARS+=( "PORTAL_EXTERNAL_URL=${PORTAL_EXTERNAL_URL}" )
[[ -n "${PORTAL_OIDC_ISSUER:-}"    ]] && INSTALL_VARS+=( "PORTAL_OIDC_ISSUER=${PORTAL_OIDC_ISSUER}" )
[[ -n "${PORTAL_OIDC_CLIENT_ID:-}" ]] && INSTALL_VARS+=( "PORTAL_OIDC_CLIENT_ID=${PORTAL_OIDC_CLIENT_ID}" )

env "${INSTALL_VARS[@]}" bash scripts/install.sh \
    --data-root    "$DATA_ROOT" \
    --compose-file "$APP_DIR/$COMPOSE_FILE"

# Injecter OIDC_CLIENT_SECRET dans /data/.env si fourni
ENV_FILE="${DATA_ROOT}/.env"
if [[ -n "${OIDC_CLIENT_SECRET:-}" ]] && [[ -f "$ENV_FILE" ]]; then
    EXISTING=$(grep -E '^OIDC_CLIENT_SECRET=.+' "$ENV_FILE" 2>/dev/null || true)
    if [[ -z "$EXISTING" ]]; then
        sed -i "s|^OIDC_CLIENT_SECRET=.*|OIDC_CLIENT_SECRET=${OIDC_CLIENT_SECRET}|" "$ENV_FILE"
        echo "    OIDC_CLIENT_SECRET injecté dans ${ENV_FILE}."
    else
        echo "    OIDC_CLIENT_SECRET déjà renseigné — non écrasé."
    fi
fi

# ─── 3) Build + démarrage de la stack ─────────────────────────────────────────
echo ""
echo "==> [3/4] Build de l'image Docker (frontend + backend)..."
docker compose -f "$COMPOSE_FILE" build

echo ""
echo "==> Arrêt de la stack en cours (si active)..."
docker compose -f "$COMPOSE_FILE" down --remove-orphans || true

echo "==> Démarrage de la stack..."
docker compose -f "$COMPOSE_FILE" up -d --remove-orphans

echo ""
docker compose -f "$COMPOSE_FILE" ps

# ─── 4) Smoke /health ─────────────────────────────────────────────────────────
echo ""
echo "==> [4/4] Smoke /health (timeout 60s)..."
SMOKE_OK=0
ELAPSED=0
while [[ $ELAPSED -lt 60 ]]; do
    if docker compose -f "$COMPOSE_FILE" exec -T portal curl -sf -m 3 "http://localhost:8080/health" &>/dev/null; then
        SMOKE_OK=1; break
    fi
    sleep 5
    ELAPSED=$(( ELAPSED + 5 ))
done

IP="$(ip -4 -o addr show scope global 2>/dev/null | awk 'NR==1 {print $4}' | cut -d/ -f1 || echo '?')"
EXTERNAL="${PORTAL_EXTERNAL_URL:-http://${IP}}"

if [[ $SMOKE_OK -eq 1 ]]; then
    cat <<EOF

══════════════════════════════════════════════════════════════════
  ✓ Portail opérationnel

  Accès  : ${EXTERNAL}
  Santé  : http://${IP}:8080/health
  Config : ${DATA_ROOT}/config.yaml
  Env    : ${DATA_ROOT}/.env

  Logs   : docker compose -f ${COMPOSE_FILE} logs -f portal
  Caddy  : docker compose -f ${COMPOSE_FILE} logs -f caddy
══════════════════════════════════════════════════════════════════
EOF
else
    cat >&2 <<EOF

══════════════════════════════════════════════════════════════════
  ✗ /health ne répond pas après 60s

  Vérifier : docker compose -f ${COMPOSE_FILE} logs --tail=80 portal
══════════════════════════════════════════════════════════════════
EOF
    exit 1
fi
