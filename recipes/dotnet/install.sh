#!/usr/bin/env bash
set -euo pipefail

# Option devcontainer — passée en variable d'environnement par le runtime
VERSION="${VERSION:-8.0}"
export DEBIAN_FRONTEND=noninteractive

echo "==> Installation du SDK .NET ${VERSION} via dotnet-install.sh"

apt-get update -q
apt-get install -y --no-install-recommends \
    ca-certificates curl libssl-dev libicu-dev zlib1g

DOTNET_ROOT="/usr/local/dotnet"
mkdir -p "$DOTNET_ROOT"

curl -fsSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh
chmod +x /tmp/dotnet-install.sh

/tmp/dotnet-install.sh \
    --channel "${VERSION}" \
    --install-dir "$DOTNET_ROOT" \
    --no-path
rm /tmp/dotnet-install.sh

ln -sf "${DOTNET_ROOT}/dotnet" /usr/local/bin/dotnet

cat > /etc/profile.d/dotnet.sh << 'PROFILE'
export DOTNET_ROOT=/usr/local/dotnet
export PATH="${DOTNET_ROOT}:${PATH}"
PROFILE
chmod +x /etc/profile.d/dotnet.sh

export DOTNET_ROOT
export PATH="${DOTNET_ROOT}:${PATH}"

echo "==> .NET ${VERSION} installé : $(dotnet --version)"
