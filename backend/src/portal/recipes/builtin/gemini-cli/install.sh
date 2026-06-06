#!/usr/bin/env bash
# GEMINI_API_KEY injectée au runtime via remoteEnv.
set -euo pipefail
VERSION="${VERSION:-latest}"
if ! command -v npm &>/dev/null; then
    echo "ERROR: npm not found. Add the node devcontainer feature before gemini-cli." >&2; exit 1
fi
echo "==> Installing Gemini CLI"
if [[ "$VERSION" == "latest" ]]; then
    npm install -g @google/gemini-cli
else
    npm install -g "@google/gemini-cli@${VERSION}"
fi
echo "==> Gemini CLI installed"
