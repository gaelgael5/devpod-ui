# start-claude-rc.sh — launcher headless, réutilise l'état persistant
#!/usr/bin/env bash
set -euo pipefail
command -v claude &>/dev/null || { echo "ERROR: claude not found." >&2; exit 1; }

unset ANTHROPIC_API_KEY

CRED="${HOME}/.claude/.credentials.json"   # chemin à confirmer : ls -la ~/.claude
if [ ! -f "$CRED" ]; then
    echo "ERROR: pas de credentials. Lance d'abord bootstrap-claude.sh (login interactif)." >&2
    exit 1
fi

echo "==> Claude Code — Remote Control (server mode)"
exec claude remote-control