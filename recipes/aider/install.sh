#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Add the python recipe first." >&2
    exit 1
fi

echo "==> Installing Aider"
if command -v pipx &>/dev/null; then
    pipx install aider-chat
else
    python3 -m pip install --quiet aider-chat
fi
echo "==> Aider: $(aider --version 2>/dev/null || echo 'installed')"
