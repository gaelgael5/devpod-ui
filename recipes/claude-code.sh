# name: Claude Code
# description: Claude Code CLI (Anthropic) — requiert ANTHROPIC_API_KEY dans l'environnement
# version: 1.0.0
#!/usr/bin/env bash
set -euo pipefail

if ! command -v npm &>/dev/null; then
    echo "ERROR: npm not found. Install Node.js first (use the Node.js LTS recipe)." >&2
    exit 1
fi

echo "==> Installing Claude Code CLI"
npm install -g @anthropic-ai/claude-code
echo "==> Claude Code CLI installed"
