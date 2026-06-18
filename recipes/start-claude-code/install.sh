#!/usr/bin/env bash
set -euo pipefail

if ! command -v claude &>/dev/null; then
    echo "ERROR: claude not found. Add the claude-code recipe first." >&2
    exit 1
fi

echo "==> Starting Claude Code in remote-control mode"
exec claude /remote-control
