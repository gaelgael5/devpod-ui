#!/usr/bin/env bash
set -euo pipefail

VERSION="${VERSION:-21}"
export DEBIAN_FRONTEND=noninteractive

echo "==> Installation d'OpenJDK ${VERSION}"

apt-get update -q
apt-get install -y --no-install-recommends \
    "openjdk-${VERSION}-jdk" \
    ca-certificates curl

cat > /etc/profile.d/java.sh << 'PROFILE'
export JAVA_HOME="$(dirname "$(dirname "$(readlink -f /usr/bin/java)")")"
export PATH="${JAVA_HOME}/bin:${PATH}"
PROFILE
chmod +x /etc/profile.d/java.sh

echo "==> $(java --version | head -1)"
