#!/usr/bin/env bash
# backend/src/portal/recipes/builtin/goose/install.sh
# Installe Goose CLI (Block AI agent).
# La clé API (ANTHROPIC_API_KEY) est injectée au runtime via remoteEnv — jamais ici.
# IMPORTANT: vérifier l'URL de release avant de déployer.
# https://github.com/block/goose/releases
set -euo pipefail

VERSION="${VERSION:-latest}"

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64) ARCH="x86_64" ;;
    aarch64|arm64) ARCH="aarch64" ;;
    *) echo "ERROR: architecture non supportée: $ARCH" >&2; exit 1 ;;
esac

if [[ "$VERSION" == "latest" ]]; then
    DOWNLOAD_URL="https://github.com/block/goose/releases/latest/download/goose-${OS}-${ARCH}"
else
    DOWNLOAD_URL="https://github.com/block/goose/releases/download/v${VERSION}/goose-${OS}-${ARCH}"
fi

echo "==> Installing Goose CLI (version: ${VERSION})"
curl -fsSL "$DOWNLOAD_URL" -o /usr/local/bin/goose
chmod +x /usr/local/bin/goose
echo "==> Goose installed"
