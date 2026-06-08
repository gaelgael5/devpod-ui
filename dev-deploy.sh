#!/usr/bin/env bash
# Raccourci racine — déploiement dev sans Caddy (portal exposé sur :80).
# Délègue à scripts/deploy-portal.sh avec le compose dev.
exec env COMPOSE_FILE=deploy/docker-compose.dev.yml \
    "$(dirname "$0")/scripts/deploy-portal.sh" "$@"
