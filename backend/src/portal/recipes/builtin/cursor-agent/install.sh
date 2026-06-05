#!/usr/bin/env bash
# backend/src/portal/recipes/builtin/cursor-agent/install.sh
# STATUT EXPÉRIMENTAL — Cursor n'a pas de CLI headless officiel publié à ce jour.
# Ce placeholder échoue intentionnellement avec un message explicite.
set -euo pipefail

echo "ERROR: cursor-agent is not yet available. Cursor does not publish a headless CLI package." >&2
echo "Remove cursor-agent from your recipe list." >&2
exit 1
