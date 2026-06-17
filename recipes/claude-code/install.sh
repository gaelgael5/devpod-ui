#!/usr/bin/env bash
set -euo pipefail

if ! command -v npm &>/dev/null; then
    echo "ERROR: npm not found. Add the nodejs recipe first." >&2
    exit 1
fi

echo "==> Installing Claude Code CLI"
npm install -g @anthropic-ai/claude-code
echo "==> Claude Code: $(claude --version 2>/dev/null || echo 'installed')"
