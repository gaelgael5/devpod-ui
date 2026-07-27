#!/usr/bin/env bash
# harden-networkd.sh — Résilience réseau des VM (enabler 59864c37, incident du 23/07).
# À exécuter en root sur la VM cible :
#   sudo bash harden-networkd.sh [iface]        (défaut : interface de la route par défaut)
#
# Trois protections, toutes idempotentes :
#   1. systemd-networkd protégé de l'OOM killer (OOMScoreAdjust=-1000) + Restart=always.
#      Le 23/07, une salve OOM a tué networkd — l'amortisseur swap adoucit, ceci immunise.
#   2. KeepConfiguration=yes sur le .network de l'interface : un échec de renouvellement
#      DHCP ou un restart de networkd ne FLUSH plus l'adresse (le 24/07, eth0 est restée
#      UP mais sans inet pendant des heures).
#   3. Timer de reprise (2 min) : si l'interface est en état failed/off ou sans IPv4,
#      `networkctl reconfigure` est rejoué automatiquement — plus besoin d'une
#      intervention manuelle depuis la console.

set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "ERREUR : exécuter en root (sudo)." >&2; exit 1; }
command -v networkctl >/dev/null || { echo "ERREUR : systemd-networkd absent." >&2; exit 1; }

IFACE="${1:-$(ip route 2>/dev/null | awk '/^default/ {print $5; exit}')}"
IFACE="${IFACE:-eth0}"
echo "==> Interface cible : $IFACE"

# ─── 1. Unité systemd-networkd : hors de portée de l'OOM killer ──────────────
install -d /etc/systemd/system/systemd-networkd.service.d
cat > /etc/systemd/system/systemd-networkd.service.d/10-portal-resilience.conf <<'EOF'
# Posé par harden-networkd.sh (enabler 59864c37) — ne pas éditer à la main.
[Service]
OOMScoreAdjust=-1000
Restart=always
RestartSec=2
EOF
echo "    OOMScoreAdjust=-1000 + Restart=always posés."

# ─── 2. KeepConfiguration=yes sur le .network de l'interface ─────────────────
# Le drop-in est cherché par basename dans /etc même si le fichier vit dans /run
# (config générée par cloud-init/netplan) — pas besoin de modifier l'original.
NET_FILE=$(networkctl status "$IFACE" 2>/dev/null \
    | sed -n 's/.*Network File: *//p' | head -1 || true)
if [[ -n "$NET_FILE" && "$NET_FILE" != "n/a" ]]; then
    DROPIN_DIR="/etc/systemd/network/$(basename "$NET_FILE").d"
    install -d "$DROPIN_DIR"
    cat > "$DROPIN_DIR/10-portal-keep.conf" <<'EOF'
# Posé par harden-networkd.sh (enabler 59864c37) — ne pas éditer à la main.
# Un échec de renouvellement DHCP ou un restart de networkd ne flush plus
# l'adresse : la config courante est conservée jusqu'à obtention d'une nouvelle.
[Network]
KeepConfiguration=yes
EOF
    echo "    KeepConfiguration=yes → $DROPIN_DIR/10-portal-keep.conf"
else
    echo "    AVERTISSEMENT : .network de $IFACE introuvable — KeepConfiguration non posé." >&2
fi

# ─── 3. Timer de reprise automatique ─────────────────────────────────────────
cat > /usr/local/sbin/portal-network-recover.sh <<EOF
#!/usr/bin/env bash
# Posé par harden-networkd.sh (enabler 59864c37) : reprise réseau automatique.
set -u
IFACE="$IFACE"
STATE=\$(networkctl list --no-legend "\$IFACE" 2>/dev/null | awk '{print \$4}')
HAS_IP=\$(ip -4 addr show "\$IFACE" 2>/dev/null | grep -c 'inet ' || true)
if [[ "\$STATE" == "failed" || "\$STATE" == "off" || "\$HAS_IP" -eq 0 ]]; then
    logger -t portal-network-recover "iface=\$IFACE state=\$STATE ipv4=\$HAS_IP -> networkctl reconfigure"
    networkctl reconfigure "\$IFACE"
fi
EOF
chmod 755 /usr/local/sbin/portal-network-recover.sh

cat > /etc/systemd/system/portal-network-recover.service <<'EOF'
[Unit]
Description=Reprise réseau automatique (enabler 59864c37)

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/portal-network-recover.sh
EOF

cat > /etc/systemd/system/portal-network-recover.timer <<'EOF'
[Unit]
Description=Vérifie l'état réseau toutes les 2 min (enabler 59864c37)

[Timer]
OnBootSec=2min
OnUnitActiveSec=2min

[Install]
WantedBy=timers.target
EOF
echo "    Timer portal-network-recover (2 min) posé."

# ─── Application ─────────────────────────────────────────────────────────────
# Ordre voulu : KeepConfiguration est déjà en place AVANT le restart de networkd,
# donc l'adresse courante survit au restart (pas de coupure).
networkctl reload 2>/dev/null || true
systemctl daemon-reload
systemctl restart systemd-networkd
systemctl enable --now portal-network-recover.timer

echo ""
echo "==> Résilience réseau appliquée sur $IFACE :"
systemctl show systemd-networkd -p OOMScoreAdjust | sed 's/^/    /'
echo "    $(networkctl list --no-legend "$IFACE" 2>/dev/null || echo 'état non lisible')"
echo "    Timer : $(systemctl is-active portal-network-recover.timer)"
