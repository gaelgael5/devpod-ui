# name: Goose CLI
# description: Install Goose CLI (Block) — agent AI autonome, télécharge un binaire, requiert une clé API LLM
# version: 1.0.0
#!/usr/bin/env bash
set -euo pipefail

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64)           ARCH="x86_64" ;;
    aarch64|arm64)    ARCH="aarch64" ;;
    *) echo "ERROR: unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

echo "==> Installing Goose CLI"
curl -fsSL "https://github.com/block/goose/releases/latest/download/goose-${OS}-${ARCH}" \
    -o /usr/local/bin/goose
chmod +x /usr/local/bin/goose
echo "==> Goose CLI installed"
