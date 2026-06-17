#!/usr/bin/env bash
set -euo pipefail

command -v apt-get >/dev/null 2>&1 || { echo "ERROR: apt-get not found. Requires Debian/Ubuntu." >&2; exit 1; }

echo "==> Installing Docker CLI"
apt-get update -qq
apt-get install -y --no-install-recommends ca-certificates curl gnupg

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update -qq
apt-get install -y --no-install-recommends docker-ce-cli
echo "==> Docker CLI: $(docker --version)"
