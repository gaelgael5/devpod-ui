#!/usr/bin/env bash
set -euo pipefail

if ! command -v npm &>/dev/null; then
    echo "ERROR: npm not found. Add the nodejs recipe first." >&2
    exit 1
fi

echo "==> Installing OpenCode CLI"
npm install -g opencode-ai
echo "==> OpenCode: $(opencode --version 2>/dev/null || echo 'installed')"
