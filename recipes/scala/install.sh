#!/usr/bin/env bash
set -euo pipefail

VERSION="${VERSION:-3}"
export DEBIAN_FRONTEND=noninteractive

echo "==> Installation de Scala ${VERSION} et sbt"

apt-get update -q
apt-get install -y --no-install-recommends ca-certificates curl gnupg

curl -fsSL "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x2EE0EA64E40A89B84B2DF73499E82A75642AC823" \
    | gpg --dearmor -o /usr/share/keyrings/sbt.gpg
echo "deb [signed-by=/usr/share/keyrings/sbt.gpg] https://repo.scala-sbt.org/scalasbt/debian all main" \
    > /etc/apt/sources.list.d/sbt.list

apt-get update -q
apt-get install -y sbt

ARCH="$(uname -m)"
case "$ARCH" in
    x86_64)  CS_ARCH="x86_64-pc-linux" ;;
    aarch64) CS_ARCH="aarch64-pc-linux" ;;
    *) echo "ERREUR: architecture non supportée : ${ARCH}" >&2; exit 1 ;;
esac

curl -fsSL "https://github.com/coursier/launchers/raw/master/cs-${CS_ARCH}.gz" \
    | gzip -d > /usr/local/bin/cs
chmod +x /usr/local/bin/cs

mkdir -p /usr/local/share/coursier/cache
chmod -R a+rwx /usr/local/share/coursier

COURSIER_CACHE=/usr/local/share/coursier/cache \
    cs install --install-dir /usr/local/bin "scala:${VERSION}.*"

echo "==> $(scala --version 2>&1 | head -1)"
echo "==> sbt : $(sbt --version 2>/dev/null | head -1 || echo 'installé')"
