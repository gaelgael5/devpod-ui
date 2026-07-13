#!/usr/bin/env bash
# dev-deploy.sh — Shim de compatibilité : délègue à deploy-portal.sh avec le
# compose de DEV. Point d'entrée historique de test1 (TESTER-MON-DEV.md) :
#   APP_DIR=/opt/workspace-portal-dev bash scripts/dev-deploy.sh dev
# Toute la logique (pull + ré-exécution, install.sh, .env, build, migrations,
# smoke) vit dans scripts/deploy-portal.sh — source de vérité unique.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

exec env \
    COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.dev.yml}" \
    DATA_ROOT="${DATA_ROOT:-/data}" \
    APP_DIR="${APP_DIR:-$(dirname "$SCRIPT_DIR")}" \
    "${SCRIPT_DIR}/deploy-portal.sh" "$@"
