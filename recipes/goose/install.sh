#!/usr/bin/env bash
set -euo pipefail

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64)        ARCH="x86_64" ;;
    aarch64|arm64) ARCH="aarch64" ;;
    *) echo "ERROR: architecture non supportée : $ARCH" >&2; exit 1 ;;
esac

echo "==> Installing Goose CLI (${OS}/${ARCH})"
curl -fsSL "https://github.com/block/goose/releases/latest/download/goose-${OS}-${ARCH}" \
    -o /usr/local/bin/goose
chmod +x /usr/local/bin/goose
echo "==> Goose CLI: $(goose --version 2>/dev/null || echo 'installed')"
