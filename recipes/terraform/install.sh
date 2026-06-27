#!/usr/bin/env bash
set -euo pipefail

VERSION="${VERSION:-latest}"
export DEBIAN_FRONTEND=noninteractive

echo "==> Installation de Terraform (version : ${VERSION})"

apt-get update -q
apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg lsb-release

curl -fsSL https://apt.releases.hashicorp.com/gpg \
    | gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg

echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] \
https://apt.releases.hashicorp.com $(lsb_release -cs) main" \
    > /etc/apt/sources.list.d/hashicorp.list

apt-get update -q

if [ "$VERSION" = "latest" ]; then
    apt-get install -y terraform
else
    apt-get install -y "terraform=${VERSION}-1"
fi

echo "==> $(terraform version | head -1)"
