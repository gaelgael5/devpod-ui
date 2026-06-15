# name: Gemini CLI
# description: Install Gemini CLI (Google) — requiert Node.js et GEMINI_API_KEY dans l'environnement
# version: 1.0.0
#!/usr/bin/env bash
set -euo pipefail

if ! command -v npm &>/dev/null; then
    echo "ERROR: npm not found. Install Node.js first (use the Node.js LTS recipe)." >&2
    exit 1
fi

echo "==> Installing Gemini CLI"
npm install -g @google/gemini-cli
echo "==> Gemini CLI installed"
