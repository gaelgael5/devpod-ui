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

if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERREUR : ce script doit être exécuté en root." >&2
    exit 1
fi

cd "$APP_DIR"

# ─── 1) Git pull ──────────────────────────────────────────────────────────────
if [[ -n "$TARGET_BRANCH" ]]; then
    echo "==> [1/3] Switch vers ${TARGET_BRANCH} + pull..."
    git fetch origin
    git checkout "$TARGET_BRANCH"
    git pull --ff-only origin "$TARGET_BRANCH"
else
    CURRENT="$(git branch --show-current)"
    echo "==> [1/3] Pull (${CURRENT})..."
    git pull --ff-only
fi

# ─── 2) Build + redémarrage ───────────────────────────────────────────────────
echo ""
echo "==> [2/3] Build de l'image Docker..."
docker compose -f "$COMPOSE_FILE" build

echo ""
echo "==> Redémarrage de la stack..."
docker compose -f "$COMPOSE_FILE" down --remove-orphans || true
docker compose -f "$COMPOSE_FILE" up -d --remove-orphans

echo ""
docker compose -f "$COMPOSE_FILE" ps

# ─── 3) Smoke /health ─────────────────────────────────────────────────────────
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
docker compose -f "$COMPOSE_FILE" logs --tail=80
