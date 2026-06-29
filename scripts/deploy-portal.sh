#!/usr/bin/env bash
# deploy-portal.sh — Déploiement du portail workspace sur une VM de dev/test.
# À exécuter en root dans la VM (directement ou via remote-deploy.ps1).
# Idempotent : peut être relancé sans danger.
#
# Usage :
#   ./scripts/deploy-portal.sh [BRANCH] [--resetdb]
#   ex : ./scripts/deploy-portal.sh main --resetdb
#
#   --resetdb  Arrête la stack, supprime les volumes DB et le fichier .env,
#              puis repart de zéro (nouveaux credentials générés).
#
# Variables d'env reconnues (toutes optionnelles si /data déjà initialisé) :
#   REPO_URL               URL git du repo        (défaut : HTTPS public gaelgael5/devpod-ui)
#   DATA_ROOT              Racine /data            (défaut : /data)
#   COMPOSE_FILE           Fichier compose cible   (défaut : deploy/docker-compose.yml)
#   PORTAL_BASE_DOMAIN     Domaine wildcard        (défaut : dev.yoops.org)
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
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.yml}"

# ─── Arguments : branche cible + flags ───────────────────────────────────────
TARGET_BRANCH=""
RESETDB=0
for arg in "$@"; do
    case "$arg" in
        --resetdb) RESETDB=1 ;;
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

# ─── --resetdb : purge complète avant toute initialisation ────────────────────
if [[ $RESETDB -eq 1 ]]; then
    echo ""
    echo "==> [--resetdb] Arrêt de la stack et suppression des volumes DB..."
    docker compose -f "$COMPOSE_FILE" down --volumes --remove-orphans 2>/dev/null || true
    echo "    Suppression des containers arrêtés résiduels..."
    docker container prune -f || true
    ENV_FILE="${DATA_ROOT}/.env"
    if [[ -f "$ENV_FILE" ]]; then
        rm -f "$ENV_FILE"
        echo "    ${ENV_FILE} supprimé."
    fi
    echo "    Reset terminé — le .env et la DB seront recréés depuis zéro."
    echo ""
fi

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

# Générer LOCAL_PASSWORD + LOCAL_PASSWORD_HASH si vides (install.sh crée le .env
# depuis .env.example mais ne génère pas les credentials locaux).
ENV_FILE="${DATA_ROOT}/.env"
if [[ -f "$ENV_FILE" ]] && \
   [[ -z "$(grep -m1 '^LOCAL_PASSWORD=' "$ENV_FILE" 2>/dev/null | cut -d= -f2-)" ]]; then
    command -v python3 &>/dev/null || apt-get install -y --no-install-recommends python3 >/dev/null 2>&1
    python3 -c "import bcrypt" 2>/dev/null || apt-get install -y --no-install-recommends python3-bcrypt >/dev/null 2>&1
    LOCAL_PASS="$(openssl rand -hex 12)"
    LOCAL_HASH="$(PASS="$LOCAL_PASS" python3 -c \
        "import bcrypt, os; print(bcrypt.hashpw(os.environ['PASS'].encode(), bcrypt.gensalt()).decode())")"
    # Doubler $ → $$ pour que bash source et docker compose ne corrompent pas le hash bcrypt.
    LOCAL_HASH_ESCAPED="$(printf '%s' "$LOCAL_HASH" | sed 's/\$/\$\$/g')"
    if grep -q '^LOCAL_PASSWORD=' "$ENV_FILE"; then
        sed -i "s|^LOCAL_PASSWORD=.*|LOCAL_PASSWORD=${LOCAL_PASS}|" "$ENV_FILE"
        sed -i "s|^LOCAL_PASSWORD_HASH=.*|LOCAL_PASSWORD_HASH=${LOCAL_HASH_ESCAPED}|" "$ENV_FILE"
    else
        printf 'LOCAL_PASSWORD=%s\nLOCAL_PASSWORD_HASH=%s\n' "$LOCAL_PASS" "$LOCAL_HASH_ESCAPED" >> "$ENV_FILE"
    fi
    echo "    LOCAL_PASSWORD généré : ${LOCAL_PASS}"
fi

# Injecter OIDC_CLIENT_SECRET dans /data/.env si fourni
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

# Détection du port 80 — si déjà utilisé, Caddy part sur 8090 pour éviter le conflit.
if [[ -z "${CADDY_DEV_PORT:-}" ]]; then
    if ss -tlnp 2>/dev/null | grep -q ':80 ' || \
       netstat -tlnp 2>/dev/null | grep -q ':80 '; then
        export CADDY_DEV_PORT="8090"
        echo "    Port 80 déjà utilisé → CADDY_DEV_PORT=8090"
    fi
fi

echo "==> Démarrage de la stack..."
docker compose -f "$COMPOSE_FILE" up -d --remove-orphans

echo ""
docker compose -f "$COMPOSE_FILE" ps

# ─── 4) Smoke /health ─────────────────────────────────────────────────────────
echo ""
echo "==> [4/4] Smoke /health (timeout 60s)..."
SMOKE_OK=0
ELAPSED=0
PORTAL_ID="$(docker compose -f "$COMPOSE_FILE" ps -q portal 2>/dev/null)"
while [[ $ELAPSED -lt 90 ]]; do
    STATUS="$(docker inspect --format='{{.State.Health.Status}}' "$PORTAL_ID" 2>/dev/null)"
    if [[ "$STATUS" == "healthy" ]]; then
        SMOKE_OK=1; break
    fi
    sleep 5
    ELAPSED=$(( ELAPSED + 5 ))
done

IP="$(ip -4 -o addr show scope global 2>/dev/null | awk 'NR==1 {print $4}' | cut -d/ -f1 || echo '?')"
EXTERNAL="${PORTAL_EXTERNAL_URL:-http://${IP}}"

# Lire les credentials locaux depuis .env (pour affichage uniquement)
_LOCAL_USER="$(grep -E '^LOCAL_USER=' "${DATA_ROOT}/.env" 2>/dev/null | cut -d= -f2- || true)"
_LOCAL_PASS="$(grep -E '^LOCAL_PASSWORD=' "${DATA_ROOT}/.env" 2>/dev/null | cut -d= -f2- || true)"

if [[ $SMOKE_OK -eq 1 ]]; then
    echo ""
    echo "══════════════════════════════════════════════════════════════════"
    echo "  ✓ Portail opérationnel"
    echo ""
    echo "  Accès  : ${EXTERNAL}"
    if [[ -n "${_LOCAL_USER:-}" && -n "${_LOCAL_PASS:-}" && -t 1 ]]; then
        echo "  Login  : ${_LOCAL_USER} / ${_LOCAL_PASS}"
        unset _LOCAL_PASS
    elif [[ -n "${_LOCAL_USER:-}" ]]; then
        echo "  Login  : ${_LOCAL_USER}  (mot de passe dans ${DATA_ROOT}/.env)"
    fi
    echo "  Santé  : http://${IP}:8080/health"
    echo "  Config : ${DATA_ROOT}/config.yaml"
    echo "  Env    : ${DATA_ROOT}/.env"
    echo ""
    echo "  Logs   : docker compose -f ${COMPOSE_FILE} logs -f"
    echo "══════════════════════════════════════════════════════════════════"
else
    cat >&2 <<EOF

══════════════════════════════════════════════════════════════════
  ✗ /health ne répond pas après 60s

  Vérifier : docker compose -f ${COMPOSE_FILE} logs --tail=80 portal
══════════════════════════════════════════════════════════════════
EOF
    exit 1
fi
