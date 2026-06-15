# name: OpenCode CLI
# description: Install OpenCode CLI — interface CLI pour LLMs de code, requiert Node.js
# version: 1.0.0
#!/usr/bin/env bash
set -euo pipefail

if ! command -v npm &>/dev/null; then
    echo "ERROR: npm not found. Install Node.js first (use the Node.js LTS recipe)." >&2
    exit 1
fi

echo "==> Installing OpenCode CLI"
npm install -g opencode-ai
echo "==> OpenCode CLI installed"
