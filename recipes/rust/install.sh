#!/usr/bin/env bash
set -euo pipefail

# Option devcontainer — passée en variable d'environnement par le runtime
CHANNEL="${CHANNEL:-stable}"
export DEBIAN_FRONTEND=noninteractive

echo "==> Installation de Rust (canal : ${CHANNEL}) via rustup"

apt-get update -q
apt-get install -y --no-install-recommends \
    ca-certificates curl gcc libssl-dev pkg-config build-essential

# Installation system-wide dans /usr/local pour tous les utilisateurs du conteneur
RUSTUP_HOME="/usr/local/rustup"
CARGO_HOME="/usr/local/cargo"
export RUSTUP_HOME CARGO_HOME

curl -fsSL https://sh.rustup.rs \
    | sh -s -- \
        --no-modify-path \
        --profile minimal \
        --default-toolchain "${CHANNEL}" \
        -y

# Accès en lecture pour tous les utilisateurs
chmod -R a+rx "$RUSTUP_HOME" "$CARGO_HOME"

# Liens symboliques globaux
for bin in cargo rustc rustup rustfmt cargo-fmt clippy-driver; do
    if [ -f "${CARGO_HOME}/bin/${bin}" ]; then
        ln -sf "${CARGO_HOME}/bin/${bin}" "/usr/local/bin/${bin}"
    fi
done

cat > /etc/profile.d/rust.sh << 'PROFILE'
export RUSTUP_HOME=/usr/local/rustup
export CARGO_HOME=/usr/local/cargo
export PATH="/usr/local/cargo/bin:${PATH}"
PROFILE
chmod +x /etc/profile.d/rust.sh

echo "==> Rust ${CHANNEL} installé : $(${CARGO_HOME}/bin/rustc --version)"
echo "==> Cargo : $(${CARGO_HOME}/bin/cargo --version)"
