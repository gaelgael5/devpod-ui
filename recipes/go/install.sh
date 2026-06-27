#!/usr/bin/env bash
set -euo pipefail

# Option devcontainer — passée en variable d'environnement par le runtime
CHANNEL="${CHANNEL:-1.23}"

ARCH="$(uname -m)"
case "$ARCH" in
    x86_64)  GOARCH="amd64" ;;
    aarch64) GOARCH="arm64" ;;
    *) echo "ERREUR: architecture non supportée : ${ARCH}" >&2; exit 1 ;;
esac

echo "==> Résolution de la dernière version patch pour Go ${CHANNEL}…"

# Requête à l'API officielle go.dev pour trouver la dernière version patch du canal
GOVERSION="$(curl -fsSL 'https://go.dev/dl/?mode=json' \
    | grep -oE '"version":"go[0-9]+\.[0-9]+\.[0-9]+"' \
    | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' \
    | grep "^${CHANNEL//./\\.}\." \
    | sort -t. -k1,1n -k2,2n -k3,3n \
    | tail -1)"

if [ -z "$GOVERSION" ]; then
    echo "ERREUR: canal Go ${CHANNEL} introuvable sur go.dev" >&2
    exit 1
fi

echo "==> Téléchargement de Go ${GOVERSION} (linux/${GOARCH})…"
curl -fsSL "https://go.dev/dl/go${GOVERSION}.linux-${GOARCH}.tar.gz" \
    -o /tmp/go.tar.gz

rm -rf /usr/local/go
tar -C /usr/local -xzf /tmp/go.tar.gz
rm /tmp/go.tar.gz

ln -sf /usr/local/go/bin/go    /usr/local/bin/go
ln -sf /usr/local/go/bin/gofmt /usr/local/bin/gofmt

cat > /etc/profile.d/go.sh << 'PROFILE'
export PATH="/usr/local/go/bin:${PATH}"
export GOPATH="${HOME}/go"
export PATH="${GOPATH}/bin:${PATH}"
PROFILE
chmod +x /etc/profile.d/go.sh

export PATH="/usr/local/go/bin:${PATH}"
echo "==> $(go version)"
