#!/usr/bin/env bash
# install-node.sh — Enrôle un nœud Docker dans le portail workspace
# Usage : curl -sSL https://dev.yoops.org/install-node.sh | bash -s -- \
#           --portal URL --token TOKEN --node-name NAME --address ADDR
#
# Pièges implémentés : §A-1 (systemd drop-in), §A-2 (SAN), §A-3 (NTP avant cert),
#                      §A-4 (mTLS), §A-5 (pare-feu)
set -euo pipefail

PORTAL=""
TOKEN=""
NODE_NAME=""
ADDRESS=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --portal)    PORTAL="$2";    shift 2 ;;
        --token)     TOKEN="$2";     shift 2 ;;
        --node-name) NODE_NAME="$2"; shift 2 ;;
        --address)   ADDRESS="$2";   shift 2 ;;
        *) echo "Argument inconnu : $1" >&2; exit 1 ;;
    esac
done

if [[ -z "$PORTAL" || -z "$TOKEN" || -z "$NODE_NAME" || -z "$ADDRESS" ]]; then
    echo "Usage : $0 --portal URL --token TOKEN --node-name NAME --address ADDR" >&2
    exit 1
fi

TLS_DIR=/etc/docker/tls
mkdir -p "$TLS_DIR"

echo "==> Vérification des outils requis..."
for cmd in curl jq openssl timedatectl; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR : $cmd est requis mais introuvable. Installez-le d'abord." >&2
        exit 1
    fi
done

# 1. Installation de Docker (idempotente)
echo "==> Installation Docker..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
else
    echo "    Docker déjà installé : $(docker --version)"
fi

# 2. Forcer NTP AVANT la génération du cert (§A-3)
# Un cert généré avec une horloge dérivée sera rejeté immédiatement.
echo "==> Synchronisation NTP..."
timedatectl set-ntp true
sleep 3
timedatectl status | grep -E "NTP|synchronized" || true

# 3. Générer la clé privée — elle ne quitte JAMAIS le nœud (§A-2, principe)
echo "==> Génération de la clé privée serveur..."
if [[ ! -f "$TLS_DIR/server-key.pem" ]]; then
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 \
        -out "$TLS_DIR/server-key.pem"
fi
chmod 600 "$TLS_DIR/server-key.pem"

# 4. Générer la CSR avec CN=NODE_NAME et SAN=IP+DNS (§A-2)
echo "==> Génération de la CSR avec SAN..."
OPENSSL_CONF=$(mktemp)
CSR_FILE=$(mktemp --suffix=.csr.pem)
trap 'rm -f "$OPENSSL_CONF" "$CSR_FILE"' EXIT

cat > "$OPENSSL_CONF" <<CONF
[req]
req_extensions   = v3_req
distinguished_name = dn
prompt           = no

[dn]
CN = ${NODE_NAME}

[v3_req]
subjectAltName = @san

[san]
CONF

# Détecter IP vs hostname pour le SAN (§A-2)
if [[ "$ADDRESS" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    printf 'IP.1 = %s\n' "$ADDRESS" >> "$OPENSSL_CONF"
else
    printf 'DNS.1 = %s\n' "$ADDRESS" >> "$OPENSSL_CONF"
fi
printf 'DNS.2 = %s\n' "$NODE_NAME" >> "$OPENSSL_CONF"

openssl req -new \
    -key "$TLS_DIR/server-key.pem" \
    -out "$CSR_FILE" \
    -config "$OPENSSL_CONF"

# 5. Appeler l'endpoint d'enrôlement
echo "==> Enrôlement auprès du portail..."
CSR_PEM=$(cat "$CSR_FILE")
RESPONSE=$(curl -sSf -X POST \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg csr "$CSR_PEM" '{"csr": $csr}')" \
    "${PORTAL}/admin/nodes/enroll")

# 6. Sauvegarder le cert et la CA
echo "$RESPONSE" | jq -r '.cert_pem' > "$TLS_DIR/server-cert.pem"
echo "$RESPONSE" | jq -r '.ca_pem'   > "$TLS_DIR/ca.pem"
echo "    Cert sauvegardé dans $TLS_DIR/"

# 7. Écrire daemon.json (§A-4 mTLS)
echo "==> Configuration daemon Docker mTLS..."
cat > /etc/docker/daemon.json <<DAEMON
{
  "hosts":      ["tcp://0.0.0.0:2376", "unix:///var/run/docker.sock"],
  "tls":        true,
  "tlsverify":  true,
  "tlscacert":  "${TLS_DIR}/ca.pem",
  "tlscert":    "${TLS_DIR}/server-cert.pem",
  "tlskey":     "${TLS_DIR}/server-key.pem"
}
DAEMON

# 8. Drop-in systemd pour neutraliser -H fd:// (§A-1 — LE piège qui bloque le restart)
# Sans ce drop-in, daemon.json + systemd provoque :
#   "unable to configure the Docker daemon ... conflicting options"
echo "==> Drop-in systemd (neutralise -H fd://)..."
OVERRIDE_DIR=/etc/systemd/system/docker.service.d
mkdir -p "$OVERRIDE_DIR"
cat > "$OVERRIDE_DIR/override.conf" <<OVERRIDE
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd
OVERRIDE
systemctl daemon-reload

# 9. Pare-feu : port 2376 uniquement depuis l'IP du portail (§A-5)
echo "==> Configuration du pare-feu..."
PORTAL_HOST=$(echo "$PORTAL" | sed 's|https\?://||;s|[:/].*||')
PORTAL_IP=$(getent hosts "$PORTAL_HOST" 2>/dev/null | awk '{print $1}' | head -1 || true)
if [[ -z "$PORTAL_IP" ]]; then
    echo "    ATTENTION : impossible de résoudre $PORTAL_HOST." >&2
    echo "    Restreignez manuellement le port 2376 à l'IP du portail." >&2
elif command -v ufw &>/dev/null; then
    ufw allow from "$PORTAL_IP" to any port 2376 comment "docker-tls portal" || true
    echo "    ufw : port 2376 autorisé depuis $PORTAL_IP"
elif command -v firewall-cmd &>/dev/null; then
    firewall-cmd --permanent \
        --add-rich-rule="rule family=ipv4 source address=${PORTAL_IP} port port=2376 protocol=tcp accept" || true
    firewall-cmd --reload
    echo "    firewalld : port 2376 autorisé depuis $PORTAL_IP"
else
    echo "    ATTENTION : aucun outil pare-feu détecté (ufw/firewall-cmd)." >&2
    echo "    Restreignez manuellement le port 2376 à $PORTAL_IP." >&2
fi

# 10. Redémarrer Docker avec la config mTLS
echo "==> Redémarrage Docker..."
systemctl restart docker

# 11. Vérification locale
sleep 2
if ss -tlnp 2>/dev/null | grep -q ':2376'; then
    echo "==> OK : daemon Docker mTLS en écoute sur le port 2376"
else
    echo "==> ERREUR : Docker n'écoute pas sur le port 2376." >&2
    echo "    Diagnostiquer : journalctl -u docker --no-pager -n 50" >&2
    exit 1
fi

echo ""
echo "Nœud ${NODE_NAME} enrôlé avec succès."
echo "Testez depuis le portail avec : devpod up --provider docker ..."
echo "Cert valide 1825 jours (§E-29). Renouvellement à prévoir avant expiration."
