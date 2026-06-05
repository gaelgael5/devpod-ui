#!/usr/bin/env bash
# Auth credentials injectées au runtime via remoteEnv.
# Vérifier le nom du package actuel : https://opencode.ai/docs
set -euo pipefail
VERSION="${VERSION:-latest}"
if ! command -v npm &>/dev/null; then
    echo "ERROR: npm not found." >&2; exit 1
fi
echo "==> Installing OpenCode CLI"
if [[ "$VERSION" == "latest" ]]; then
    npm install -g opencode-ai
else
    npm install -g "opencode-ai@${VERSION}"
fi
echo "==> OpenCode CLI installed"
