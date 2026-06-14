# name: Git
# description: Configure Git avec user.name et user.email via variables d'environnement
# version: 1.0.0
#!/usr/bin/env bash
set -e
echo "Configuring Git..."
git config --global user.name "${GIT_USER_NAME:-dev}"
git config --global user.email "${GIT_USER_EMAIL:-dev@example.com}"
echo "Git configured."
