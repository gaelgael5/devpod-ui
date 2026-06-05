#!/usr/bin/env bash
# ANTHROPIC_API_KEY injectée au runtime via remoteEnv.
# Vérifier la commande d'installation actuelle : https://block.github.io/goose/docs/installation
set -euo pipefail
echo "==> Installing Goose CLI"
curl -fsSL https://github.com/block/goose/releases/latest/download/goose-installer.sh | bash
echo "==> Goose CLI installed"
