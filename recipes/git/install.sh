#!/usr/bin/env bash
set -euo pipefail

echo "==> Configuring Git"
git config --global user.name  "${GIT_USER_NAME:-dev}"
git config --global user.email "${GIT_USER_EMAIL:-dev@example.com}"
git config --global init.defaultBranch main
echo "==> Git configured: $(git config --global user.name) <$(git config --global user.email)>"
