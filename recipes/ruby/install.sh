#!/usr/bin/env bash
set -euo pipefail

VERSION="${VERSION:-3.3.6}"
export DEBIAN_FRONTEND=noninteractive

echo "==> Installation de Ruby ${VERSION} via rbenv"

apt-get update -q
apt-get install -y --no-install-recommends \
    git curl ca-certificates \
    build-essential libssl-dev libreadline-dev zlib1g-dev \
    libyaml-dev libffi-dev libgdbm-dev

RBENV_ROOT=/usr/local/rbenv

git clone https://github.com/rbenv/rbenv.git "$RBENV_ROOT"
git clone https://github.com/rbenv/ruby-build.git "${RBENV_ROOT}/plugins/ruby-build"
chmod -R a+rx "$RBENV_ROOT"

cat > /etc/profile.d/rbenv.sh << 'PROFILE'
export RBENV_ROOT=/usr/local/rbenv
export PATH="${RBENV_ROOT}/bin:${RBENV_ROOT}/shims:${PATH}"
PROFILE
chmod +x /etc/profile.d/rbenv.sh

export PATH="${RBENV_ROOT}/bin:${RBENV_ROOT}/shims:${PATH}"

RBENV_ROOT="$RBENV_ROOT" rbenv install "$VERSION"
RBENV_ROOT="$RBENV_ROOT" rbenv global "$VERSION"
rbenv rehash

gem install bundler
echo "==> $(ruby --version)"
echo "==> Bundler : $(bundler --version)"
