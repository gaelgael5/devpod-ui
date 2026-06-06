#!/usr/bin/env bash
# setup-docker-node.sh — Configuration post-installation d'une VM nœud Docker (étapes 3 et 4).
# À exécuter en root DANS la VM, via SSH — pas sur le host Proxmox VE.
#
# Usage :
#   bash setup-docker-node.sh --portal-ip <IP> [OPTIONS]
#   curl -sSL https://raw.githubusercontent.com/gaelgael5/devpod-ui/refs/heads/main/scripts/setup-docker-node.sh \
#     | bash -s -- --portal-ip <IP> [OPTIONS]
#
# Argument obligatoire :
#   --portal-ip IP    Adresse IP du serveur portail (règle ufw entrante sur le port 2376)
#
# Options :
#   --portal-url URL  URL de test de connectivité sortante (défaut : https://dev.yoops.org/health)
#   --ssh-key "..."   Clé publique SSH à ajouter à /root/.ssh/authorized_keys
#   --skip-upgrade    Ne pas exécuter apt-get upgrade (air-gapped ou déploiement rapide)
#   --skip-ufw        Ne pas configurer ufw (si un pare-feu tiers est déjà en place)

set -euo pipefail
IFS=$'\n\t'

# ─── Valeurs par défaut ────────────────────────────────────────────────────────
PORTAL_IP=""
PORTAL_URL="https://dev.yoops.org/health"
SSH_KEY=""
SKIP_UPGRADE=0
SKIP_UFW=0

# ─── Analyse des arguments ────────────────────────────────────────────────────
if [[ $# -lt 1 ]]; then
    echo "ERREUR : --portal-ip est obligatoire." >&2
    echo "Usage : bash $0 --portal-ip <IP> [--portal-url URL] [--ssh-key \"clé\"] [--skip-upgrade] [--skip-ufw]" >&2
    exit 1
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --portal-ip)    PORTAL_IP="$2";   shift 2 ;;
        --portal-url)   PORTAL_URL="$2";  shift 2 ;;
        --ssh-key)      SSH_KEY="$2";     shift 2 ;;
        --skip-upgrade) SKIP_UPGRADE=1;   shift   ;;
        --skip-ufw)     SKIP_UFW=1;       shift   ;;
        *)
            echo "ERREUR : option inconnue : $1" >&2
            echo "Options supportées : --portal-ip, --portal-url, --ssh-key, --skip-upgrade, --skip-ufw" >&2
            exit 1
            ;;
    esac
done

# ─── Prérequis ────────────────────────────────────────────────────────────────
echo "==> Vérification des prérequis..."

# Doit tourner en root
if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERREUR : ce script doit être exécuté en root (ou via sudo)." >&2
    exit 1
fi

# Ne doit PAS tourner sur un host Proxmox VE
if command -v qm &>/dev/null; then
    echo "ERREUR : ce script doit être exécuté DANS la VM nœud, pas sur le host Proxmox VE." >&2
    exit 1
fi

# Valider --portal-ip (format IPv4)
if [[ -z "$PORTAL_IP" ]]; then
    echo "ERREUR : --portal-ip est obligatoire." >&2
    echo "Usage : bash $0 --portal-ip <IP>" >&2
    exit 1
fi
if ! [[ "$PORTAL_IP" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
    echo "ERREUR : --portal-ip '$PORTAL_IP' n'est pas une adresse IPv4 valide." >&2
    exit 1
fi

echo "    Exécution en root       : OK"
echo "    IP du portail           : $PORTAL_IP"
echo "    URL test connectivité   : $PORTAL_URL"
[[ $SKIP_UPGRADE -eq 1 ]] && echo "    apt upgrade             : ignoré (--skip-upgrade)"
[[ $SKIP_UFW     -eq 1 ]] && echo "    ufw                     : ignoré (--skip-ufw)"
echo ""

# ─── 3.1 — Mises à jour ──────────────────────────────────────────────────────
echo "==> 3.1 — Mise à jour des paquets..."
apt-get update -q

if [[ $SKIP_UPGRADE -eq 0 ]]; then
    DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -q
    echo "    Mise à jour terminée."
else
    echo "    Ignoré (--skip-upgrade)."
fi
echo ""

# ─── 3.2 — Outils requis par le script d'enrôlement ─────────────────────────
echo "==> 3.2 — Installation des outils requis..."
DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
    curl \
    jq \
    openssl \
    ca-certificates \
    gnupg \
    lsb-release \
    systemd-timesyncd

echo "    Versions installées :"
echo "      curl    : $(curl --version | head -1)"
echo "      jq      : $(jq --version)"
echo "      openssl : $(openssl version)"
echo ""

# ─── 3.3 — Synchronisation NTP ───────────────────────────────────────────────
echo "==> 3.3 — Configuration de la synchronisation NTP..."
systemctl enable --now systemd-timesyncd
timedatectl set-ntp true

echo "    Attente de la synchronisation (max 60 s)..."
NTP_OK=0
ELAPSED=0
while [[ $ELAPSED -lt 60 ]]; do
    if timedatectl show --property=NTPSynchronized --value 2>/dev/null | grep -qx "yes"; then
        NTP_OK=1
        break
    fi
    sleep 5
    ELAPSED=$(( ELAPSED + 5 ))
done

if [[ $NTP_OK -eq 0 ]]; then
    echo "AVERTISSEMENT : NTP non synchronisé après 60 s." >&2
    echo "  Ce n'est pas bloquant maintenant, mais doit être résolu avant l'enrôlement." >&2
    echo "  Diagnostic : timedatectl timesync-status" >&2
else
    echo "    NTP synchronisé : OK"
fi
echo ""

# ─── 3.4 — Durcissement SSH ──────────────────────────────────────────────────
echo "==> 3.4 — Durcissement SSH..."

# Ajouter la clé SSH fournie si elle n'est pas déjà présente
if [[ -n "$SSH_KEY" ]]; then
    mkdir -p /root/.ssh
    chmod 700 /root/.ssh
    touch /root/.ssh/authorized_keys
    chmod 600 /root/.ssh/authorized_keys
    if grep -qF "$SSH_KEY" /root/.ssh/authorized_keys 2>/dev/null; then
        echo "    Clé SSH déjà présente — non dupliquée."
    else
        echo "$SSH_KEY" >> /root/.ssh/authorized_keys
        echo "    Clé SSH ajoutée à /root/.ssh/authorized_keys."
    fi
fi

SSHD_CFG="/etc/ssh/sshd_config"

# Désactiver l'authentification par mot de passe
if grep -qE '^#?PasswordAuthentication' "$SSHD_CFG"; then
    sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' "$SSHD_CFG"
else
    echo "PasswordAuthentication no" >> "$SSHD_CFG"
fi

# Sécuriser l'accès root (clé uniquement, pas de mot de passe)
if grep -qE '^#?PermitRootLogin' "$SSHD_CFG"; then
    sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' "$SSHD_CFG"
else
    echo "PermitRootLogin prohibit-password" >> "$SSHD_CFG"
fi

# Valider la configuration avant de recharger
sshd -t || {
    echo "ERREUR : configuration sshd invalide après modification." >&2
    echo "  Vérifier manuellement : sshd -T | grep -E 'passwordauthentication|permitrootlogin'" >&2
    exit 1
}

# Identifier le service SSH (Debian 12 : "ssh" ; autres distributions : "sshd")
SSH_SERVICE=""
for svc in ssh sshd; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        SSH_SERVICE="$svc"
        break
    fi
done
if [[ -z "$SSH_SERVICE" ]]; then
    echo "ERREUR : service SSH introuvable (ni 'ssh' ni 'sshd' n'est actif)." >&2
    exit 1
fi
systemctl reload "$SSH_SERVICE"

echo "    PasswordAuthentication : no"
echo "    PermitRootLogin        : prohibit-password"
echo "    Service '$SSH_SERVICE' rechargé."
echo ""

# ─── 3.5 — Pare-feu ufw ──────────────────────────────────────────────────────
if [[ $SKIP_UFW -eq 0 ]]; then
    echo "==> 3.5 — Configuration du pare-feu (ufw)..."
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q ufw

    ufw allow 22/tcp    comment "SSH"                                                        >/dev/null
    ufw allow from "$PORTAL_IP" to any port 2376 proto tcp comment "Docker mTLS — portail" >/dev/null
    ufw --force enable

    echo "    Règles actives :"
    ufw status numbered | grep -v "^$\|^Status" | sed 's/^/      /'
    echo ""
else
    echo "==> 3.5 — Pare-feu : ignoré (--skip-ufw)."
    echo "    S'assurer manuellement que :"
    echo "      - le port 22/tcp est ouvert (SSH)"
    echo "      - le port 2376/tcp est restreint à $PORTAL_IP"
    echo ""
fi

# ─── Étape 4 — Vérifications avant enrôlement ────────────────────────────────
echo "==> Étape 4 — Vérifications avant enrôlement..."
WARNINGS=0

# 4.1 — Adresses IP actives
echo ""
echo "  [4.1] Adresses IP configurées :"
ip -4 addr show scope global | grep inet | sed 's/^/         /'
echo "        → Vérifier qu'aucune adresse n'est issue d'un bail DHCP résiduel."

# 4.2 — Hostname
HOSTNAME_VAL=$(hostname)
echo ""
echo "  [4.2] Hostname : $HOSTNAME_VAL"
if [[ -z "$HOSTNAME_VAL" || "$HOSTNAME_VAL" == "localhost" || "$HOSTNAME_VAL" == "debian" ]]; then
    echo "        AVERTISSEMENT : hostname non défini ou générique ('$HOSTNAME_VAL')." >&2
    echo "        Corriger : hostnamectl set-hostname <nom-du-noeud>" >&2
    WARNINGS=$(( WARNINGS + 1 ))
else
    echo "        OK — doit correspondre exactement au --node-name lors de l'enrôlement."
fi

# 4.3 — Outils présents
echo ""
echo "  [4.3] Présence des outils requis :"
for tool in curl jq openssl timedatectl; do
    if command -v "$tool" &>/dev/null; then
        echo "        $tool : OK"
    else
        echo "        $tool : MANQUANT" >&2
        WARNINGS=$(( WARNINGS + 1 ))
    fi
done

# 4.4 — NTP synchronisé
echo ""
echo "  [4.4] Synchronisation NTP :"
if timedatectl show --property=NTPSynchronized --value 2>/dev/null | grep -qx "yes"; then
    echo "        OK — horloge synchronisée."
else
    echo "        AVERTISSEMENT : NTP non synchronisé." >&2
    echo "        Diagnostic : systemctl status systemd-timesyncd && timedatectl timesync-status" >&2
    WARNINGS=$(( WARNINGS + 1 ))
fi

# 4.5 — Port 2376 non ouvert (Docker pas encore installé)
echo ""
echo "  [4.5] Port 2376 — doit être fermé à ce stade :"
if ss -tlnp 2>/dev/null | grep -q ':2376'; then
    echo "        AVERTISSEMENT : un processus écoute déjà sur le port 2376." >&2
    echo "        Docker ne devrait pas être installé avant l'enrôlement." >&2
    WARNINGS=$(( WARNINGS + 1 ))
else
    echo "        OK — port 2376 non ouvert."
fi

# 4.6 — Connectivité sortante vers le portail
echo ""
echo "  [4.6] Connectivité sortante ($PORTAL_URL) :"
if curl -sf --max-time 10 "$PORTAL_URL" &>/dev/null; then
    echo "        OK — portail joignable."
else
    echo "        AVERTISSEMENT : portail non joignable à $PORTAL_URL" >&2
    echo "        Vérifier : résolution DNS, certificat TLS, pare-feu sortant." >&2
    WARNINGS=$(( WARNINGS + 1 ))
fi

# ─── Résumé ───────────────────────────────────────────────────────────────────
echo ""
echo "======================================================"
if [[ $WARNINGS -eq 0 ]]; then
    echo "  Configuration terminée — VM prête pour l'enrôlement."
else
    echo "  Configuration terminée avec $WARNINGS avertissement(s)."
    echo "  Corriger les points signalés avant de procéder à l'enrôlement."
fi
echo "======================================================"
echo ""
echo "Prochaine étape :"
echo "  Premier nœud  → documentations/fr/installation-first-node.md"
echo "  Nœud suivant  → documentations/fr/installation-second-node.md"
echo ""
