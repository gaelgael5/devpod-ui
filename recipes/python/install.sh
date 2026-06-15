#!/usr/bin/env bash
set -euo pipefail

# Option devcontainer — passée en variable d'environnement par le runtime
VERSION="${VERSION:-3.12}"
export DEBIAN_FRONTEND=noninteractive

echo "==> Installation de Python ${VERSION} via deadsnakes PPA"

apt-get update -q
apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg software-properties-common

add-apt-repository -y ppa:deadsnakes/ppa
apt-get update -q
apt-get install -y --no-install-recommends \
    "python${VERSION}" \
    "python${VERSION}-venv" \
    "python${VERSION}-dev"

# Définir python3 / python comme alias vers la version demandée
update-alternatives --install /usr/bin/python3 python3 \
    "/usr/bin/python${VERSION}" 100
update-alternatives --set python3 "/usr/bin/python${VERSION}"
ln -sf /usr/bin/python3 /usr/bin/python

# Bootstrap pip (ensurepip non inclus dans tous les paquets deadsnakes)
curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
"python${VERSION}" /tmp/get-pip.py
rm /tmp/get-pip.py
"python${VERSION}" -m pip install --upgrade pip setuptools wheel

echo "==> Python ${VERSION} installé : $(python3 --version)"
echo "==> pip : $(pip3 --version)"
