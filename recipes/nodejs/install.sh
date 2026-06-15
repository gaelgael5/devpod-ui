#!/usr/bin/env bash
set -euo pipefail

VERSION="${VERSION:-22}"
export DEBIAN_FRONTEND=noninteractive

echo "==> Installation de Node.js ${VERSION}.x via NodeSource"

apt-get update -q
apt-get install -y --no-install-recommends ca-certificates curl gnupg

curl -fsSL "https://deb.nodesource.com/setup_${VERSION}.x" | bash -
apt-get install -y nodejs

corepack enable

echo "==> Node.js : $(node --version)"
echo "==> npm    : $(npm --version)"
