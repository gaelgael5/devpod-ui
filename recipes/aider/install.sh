#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Add the python recipe first." >&2
    exit 1
fi

echo "==> Installing Aider in /opt/aider (isolated venv)"
python3 -m venv /opt/aider
/opt/aider/bin/pip install --no-cache-dir aider-chat

ln -sf /opt/aider/bin/aider /usr/local/bin/aider

echo "==> Aider: $(aider --version 2>/dev/null || echo 'installed')"
