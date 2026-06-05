#!/usr/bin/env bash
# ANTHROPIC_API_KEY (ou OPENAI_API_KEY) injectée au runtime via remoteEnv.
set -euo pipefail
VERSION="${VERSION:-latest}"
echo "==> Installing aider-chat"
if [[ "$VERSION" == "latest" ]]; then
    pip install --quiet aider-chat
else
    pip install --quiet "aider-chat==${VERSION}"
fi
echo "==> aider-chat installed"
