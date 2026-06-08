#!/usr/bin/env bash
# Raccourci racine — déploiement dev sans Caddy (portal exposé sur :80).
# Toujours sur la branche courante (pas d'argument de branche).
exec env COMPOSE_FILE=deploy/docker-compose.dev.yml \
    "$(dirname "$0")/scripts/deploy-portal.sh"
