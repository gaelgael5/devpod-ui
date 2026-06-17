#!/usr/bin/env bash
set -euo pipefail

if ! command -v npm &>/dev/null; then
    echo "ERROR: npm not found. Add the nodejs recipe first." >&2
    exit 1
fi

echo "==> Installing Claude Code CLI"
npm install -g @anthropic-ai/claude-code

# Le binaire peut atterrir dans le prefix npm (variable selon nvm vs system node).
# On s'assure qu'il est accessible depuis /usr/local/bin.
CLAUDE_BIN="$(npm config get prefix)/bin/claude"
if [ -f "$CLAUDE_BIN" ] && [ ! -e /usr/local/bin/claude ]; then
    ln -sf "$CLAUDE_BIN" /usr/local/bin/claude
fi

echo "==> Claude Code: $(claude --version 2>/dev/null || echo 'installed')"
