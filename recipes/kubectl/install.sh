#!/usr/bin/env bash
set -euo pipefail

KUBECTL_VERSION="${KUBECTL_VERSION:-1.30}"
export DEBIAN_FRONTEND=noninteractive

echo "==> Installation de kubectl ${KUBECTL_VERSION} et Helm"

apt-get update -q
apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg apt-transport-https

mkdir -p /etc/apt/keyrings
curl -fsSL "https://pkgs.k8s.io/core:/stable:/v${KUBECTL_VERSION}/deb/Release.key" \
    | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg

echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] \
https://pkgs.k8s.io/core:/stable:/v${KUBECTL_VERSION}/deb/ /" \
    > /etc/apt/sources.list.d/kubernetes.list

apt-get update -q
apt-get install -y kubectl

curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

echo "==> kubectl : $(kubectl version --client 2>/dev/null | head -1)"
echo "==> Helm    : $(helm version --short)"
