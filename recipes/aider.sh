# name: Aider
# description: Install Aider — AI pair programmer en CLI, requiert Python et ANTHROPIC_API_KEY ou OPENAI_API_KEY
# version: 1.0.0
#!/usr/bin/env bash
set -euo pipefail

if ! command -v pip &>/dev/null && ! command -v pip3 &>/dev/null; then
    echo "ERROR: pip not found. Install Python first (use the Python 3.12 recipe)." >&2
    exit 1
fi

PIP_CMD=$(command -v pip3 || command -v pip)
echo "==> Installing Aider"
$PIP_CMD install --quiet aider-chat
echo "==> Aider installed"
