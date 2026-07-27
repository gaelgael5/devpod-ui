#!/usr/bin/env bash
# dev-deploy.sh — Shim de compatibilité : délègue à scripts/deploy-portal.sh
# avec le compose de DEV (portal exposé sur :8080, Caddy dev). Point d'entrée
# historique du host live et de remote-deploy.ps1.
# Toute la logique (pull + ré-exécution, install.sh, .env, build, migrations,
# smoke) vit dans scripts/deploy-portal.sh — source de vérité unique.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

exec env \
    COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.dev.yml}" \
    DATA_ROOT="${DATA_ROOT:-/data}" \
    APP_DIR="${APP_DIR:-$SCRIPT_DIR}" \
    "${SCRIPT_DIR}/scripts/deploy-portal.sh" "$@"
