#!/usr/bin/env bash
# Lance Claude Code en mode remote-control (MCP socket).
set -euo pipefail

command -v claude &>/dev/null || { echo "ERROR: claude not found — installer la recette claude-code d'abord." >&2; exit 1; }

CRED="${HOME}/.claude/.credentials.json"
if [ ! -f "$CRED" ]; then
    echo "ERROR: pas de credentials Claude."
    echo "Lance d'abord : claude login"
    exit 1
fi

echo "==> Claude Code — démarrage remote-control (MCP socket)..."
exec claude remote-control
