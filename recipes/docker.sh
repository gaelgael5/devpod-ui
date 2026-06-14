# name: Docker CLI
# description: Installe le client Docker CLI (sans daemon)
# version: 1.0.0
#!/usr/bin/env bash
set -e
echo "Installing Docker CLI..."
apt-get update -qq
apt-get install -y --no-install-recommends docker-ce-cli
echo "Docker CLI $(docker --version) installed."
