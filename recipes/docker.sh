# name: Docker CLI
# description: Install Installe le client Docker CLI (sans daemon)
# version: 1.0.0
#!/usr/bin/env bash
set -e
command -v apt-get >/dev/null 2>&1 || { echo "Error: apt-get not found. This script requires Debian/Ubuntu." >&2; exit 1; }
echo "Installing Docker CLI..."
apt-get update -qq
apt-get install -y --no-install-recommends docker-ce-cli
echo "Docker CLI $(docker --version) installed."
