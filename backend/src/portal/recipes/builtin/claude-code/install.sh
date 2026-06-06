#!/usr/bin/env bash
# Installe Claude Code CLI (Anthropic).
# ANTHROPIC_API_KEY est injectée au runtime via remoteEnv — jamais ici.
set -euo pipefail

VERSION="${VERSION:-latest}"

if ! command -v npm &>/dev/null; then
    echo "ERROR: npm not found. Add the node devcontainer feature before claude-code." >&2
    exit 1
fi

echo "==> Installing Claude Code CLI (version: ${VERSION})"
if [[ "$VERSION" == "latest" ]]; then
    npm install -g @anthropic-ai/claude-code
else
    npm install -g "@anthropic-ai/claude-code@${VERSION}"
fi

echo "==> Claude Code CLI installed"
