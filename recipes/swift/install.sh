#!/usr/bin/env bash
set -euo pipefail

VERSION="${VERSION:-6.0}"
export DEBIAN_FRONTEND=noninteractive

echo "==> Installation de Swift ${VERSION}"

apt-get update -q
apt-get install -y --no-install-recommends \
    ca-certificates curl lsb-release \
    binutils libc6-dev libcurl4-openssl-dev libedit2 \
    libgcc-13-dev libpython3-dev libsqlite3-0 \
    libstdc++-13-dev libxml2-dev libz3-dev pkg-config \
    tzdata unzip zlib1g-dev

ARCH="$(uname -m)"
UBUNTU_VERSION="$(lsb_release -sr | tr -d .)"
UBUNTU_FULL="$(lsb_release -sr)"

case "$ARCH" in
    x86_64)
        SWIFT_DIR="ubuntu${UBUNTU_VERSION}"
        SWIFT_PKG="swift-${VERSION}-RELEASE-ubuntu${UBUNTU_FULL}"
        ;;
    aarch64)
        SWIFT_DIR="ubuntu${UBUNTU_VERSION}-aarch64"
        SWIFT_PKG="swift-${VERSION}-RELEASE-ubuntu${UBUNTU_FULL}-aarch64"
        ;;
    *) echo "ERREUR: architecture non supportée : ${ARCH}" >&2; exit 1 ;;
esac

curl -fsSL \
    "https://download.swift.org/swift-${VERSION}-release/${SWIFT_DIR}/${SWIFT_PKG}.tar.gz" \
    -o /tmp/swift.tar.gz

tar -C /usr/local -xzf /tmp/swift.tar.gz
rm /tmp/swift.tar.gz
mv "/usr/local/${SWIFT_PKG}" /usr/local/swift

cat > /etc/profile.d/swift.sh << 'PROFILE'
export PATH="/usr/local/swift/usr/bin:${PATH}"
PROFILE
chmod +x /etc/profile.d/swift.sh

export PATH="/usr/local/swift/usr/bin:${PATH}"
echo "==> $(swift --version | head -1)"
