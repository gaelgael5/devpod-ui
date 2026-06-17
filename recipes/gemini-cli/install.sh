#!/usr/bin/env bash
set -euo pipefail

if ! command -v npm &>/dev/null; then
    echo "ERROR: npm not found. Add the nodejs recipe first." >&2
    exit 1
fi

echo "==> Installing Gemini CLI"
npm install -g @google/gemini-cli
echo "==> Gemini CLI: $(gemini --version 2>/dev/null || echo 'installed')"
