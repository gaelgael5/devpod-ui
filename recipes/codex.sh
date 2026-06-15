# name: Codex CLI
# description: Install OpenAI Codex CLI — requiert Node.js et OPENAI_API_KEY dans l'environnement
# version: 1.0.0
#!/usr/bin/env bash
set -euo pipefail

if ! command -v npm &>/dev/null; then
    echo "ERROR: npm not found. Install Node.js first (use the Node.js LTS recipe)." >&2
    exit 1
fi

echo "==> Installing OpenAI Codex CLI"
npm install -g @openai/codex
echo "==> Codex CLI installed"
