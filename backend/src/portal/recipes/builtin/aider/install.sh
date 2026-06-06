#!/usr/bin/env bash
# backend/src/portal/recipes/builtin/aider/install.sh
# ANTHROPIC_API_KEY (ou OPENAI_API_KEY) injectée au runtime via remoteEnv — jamais ici.
set -euo pipefail

VERSION="${VERSION:-latest}"

if ! command -v pip &>/dev/null && ! command -v pip3 &>/dev/null; then
    echo "ERROR: pip not found. Add a Python devcontainer feature before aider." >&2
    exit 1
fi

PIP_CMD=$(command -v pip3 || command -v pip)
echo "==> Installing Aider CLI (version: ${VERSION})"
if [[ "$VERSION" == "latest" ]]; then
    $PIP_CMD install --quiet aider-chat
else
    $PIP_CMD install --quiet "aider-chat==${VERSION}"
fi
echo "==> Aider installed"
