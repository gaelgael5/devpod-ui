#!/usr/bin/env bash
# OPENAI_API_KEY injectée au runtime via remoteEnv.
set -euo pipefail
VERSION="${VERSION:-latest}"
if ! command -v npm &>/dev/null; then
    echo "ERROR: npm not found." >&2; exit 1
fi
echo "==> Installing OpenAI Codex CLI"
if [[ "$VERSION" == "latest" ]]; then
    npm install -g @openai/codex
else
    npm install -g "@openai/codex@${VERSION}"
fi
echo "==> Codex CLI installed"
