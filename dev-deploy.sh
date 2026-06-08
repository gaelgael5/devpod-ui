#!/usr/bin/env bash
# Raccourci racine — délègue à scripts/deploy-portal.sh
exec "$(dirname "$0")/scripts/deploy-portal.sh" "$@"
