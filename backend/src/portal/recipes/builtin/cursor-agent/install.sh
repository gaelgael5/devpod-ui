#!/usr/bin/env bash
# Cursor agent headless — pas l'éditeur desktop (inutile en VS Code-in-browser).
# Auth credentials injectées au runtime via remoteEnv.
# Vérifier le nom du package actuel avant déploiement.
set -euo pipefail
VERSION="${VERSION:-latest}"
if ! command -v npm &>/dev/null; then
    echo "ERROR: npm not found." >&2; exit 1
fi
echo "==> Installing Cursor Agent (headless)"
if [[ "$VERSION" == "latest" ]]; then
    npm install -g @cursor/agent
else
    npm install -g "@cursor/agent@${VERSION}"
fi
echo "==> Cursor Agent installed"
