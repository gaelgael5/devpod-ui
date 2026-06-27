#!/usr/bin/env bash
set -euo pipefail

VERSION="${VERSION:-8.3}"
export DEBIAN_FRONTEND=noninteractive

echo "==> Installation de PHP ${VERSION} via PPA ondrej/php"

apt-get update -q
apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg software-properties-common

add-apt-repository -y ppa:ondrej/php
apt-get update -q

apt-get install -y --no-install-recommends \
    "php${VERSION}" \
    "php${VERSION}-cli" \
    "php${VERSION}-mbstring" \
    "php${VERSION}-xml" \
    "php${VERSION}-curl" \
    "php${VERSION}-zip" \
    "php${VERSION}-intl" \
    "php${VERSION}-bcmath"

update-alternatives --install /usr/bin/php php "/usr/bin/php${VERSION}" 100
update-alternatives --set php "/usr/bin/php${VERSION}"

curl -fsSL https://getcomposer.org/installer \
    | php -- --install-dir=/usr/local/bin --filename=composer

echo "==> $(php --version | head -1)"
echo "==> $(composer --version)"
