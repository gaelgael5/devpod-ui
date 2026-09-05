#!/usr/bin/env bash
# configure-node.sh — Configure un nœud Docker sur une machine Debian joignable en SSH
# (étapes A.10 à A.12, extraites de proxmox-clone-vm-node.sh — enabler 7c739d1f).
# Portable : ne connaît ni VMID, ni nœud Proxmox, ni template — seulement le
# triplet (adresse, user, clé privée). Fonctionne sur n'importe quelle machine
# Debian : VM Proxmox, VM cloud, NUC enrôlé à la main.
#
# Rejouable : chaque étape teste l'existant avant d'agir (swapfile, fstab,
# builder buildx, groupes, sysctl) ; un second passage ne duplique rien.
#
# Usage :
#   bash configure-node.sh --address <ip> --user <user> --key <clé_privée> \
#       [--node-name <nom>] [--swap <pct>] [--cpu-type <modele>] \
#       [--portal-url <url>] [--portal-token <token>]
#
# Reconfigurer un host existant du parc (aucune création de machine) :
#   bash configure-node.sh --address 192.168.10.x --user debian \
#       --key /data/keys/hosts/<name>_ed25519 --node-name <name>
#
# Options :
#   --address IP      Adresse IP (ou hostname) de la machine cible   [obligatoire]
#   --user USER       Utilisateur SSH (sudoer, ou root)              [obligatoire]
#   --key FICHIER     Clé privée SSH                                 [obligatoire]
#   --node-name NOM   Nom attendu du nœud (hostname + enrôlement portail)
#   --swap PCT        Swapfile en % de la RAM effective (défaut : 25 ; 0 = désactivé)
#   --cpu-type MODELE Modèle CPU demandé à la création (informative : affine le
#                     message quand /dev/kvm est absent)
#   --portal-url URL  URL du portail (déclenche l'enrôlement A.12 avec --portal-token)
#   --portal-token T  Jeton d'enrôlement du portail
#
# Contrat de sortie : code 0 si tout est passé ; sinon code d'erreur, avec
# l'étape atteinte sur stderr. Il n'écrit AUCUN JSON : le descripteur de la
# machine est composé par l'appelant (clone-vm-node.sh, module IaC, ...).

set -euo pipefail
IFS=$'\n\t'

IP_ADDR=""
CI_USER=""
SSH_PRIVATE_KEY=""
NODE_NAME=""
CPU_TYPE=""
PORTAL_URL=""
# Accepté en variable d'environnement : un argv est lisible par tout processus
# local (`ps auxww`). L'option --portal-token reste un repli de compatibilité.
PORTAL_TOKEN="${PORTAL_TOKEN:-}"
# Swapfile d'urgence (enabler 74ad4fdf) : sans swap, un pic mémoire transitoire
# déclenche l'OOM killer immédiatement (incident du 23/07 : networkd tué, host
# injoignable). 25 % de la RAM, borné, swappiness bas = airbag, pas matelas.
SWAP_PERCENT=25
SWAP_MIN_MB=512
SWAP_MAX_MB=8192
SWAPPINESS=10

while [[ $# -gt 0 ]]; do
    case "$1" in
        --address)      IP_ADDR="$2";         shift 2 ;;
        --user)         CI_USER="$2";         shift 2 ;;
        --key)          SSH_PRIVATE_KEY="$2"; shift 2 ;;
        --node-name)    NODE_NAME="$2";       shift 2 ;;
        --swap)         SWAP_PERCENT="$2";    shift 2 ;;
        --cpu-type)     CPU_TYPE="$2";        shift 2 ;;
        --portal-url)   PORTAL_URL="$2";      shift 2 ;;
        --portal-token) PORTAL_TOKEN="$2";    shift 2 ;;
        *)
            echo "ERREUR : option inconnue : $1" >&2
            echo "Options : --address --user --key --node-name --swap --cpu-type --portal-url --portal-token" >&2
            exit 1
            ;;
    esac
done

[[ -n "$IP_ADDR" ]]  || { echo "ERREUR : --address est obligatoire." >&2; exit 1; }
[[ -n "$CI_USER" ]]  || { echo "ERREUR : --user est obligatoire." >&2; exit 1; }
[[ -n "$SSH_PRIVATE_KEY" ]] || { echo "ERREUR : --key est obligatoire." >&2; exit 1; }
[[ -f "$SSH_PRIVATE_KEY" ]] || {
    echo "ERREUR : clé privée introuvable : $SSH_PRIVATE_KEY" >&2
    exit 1
}
if [[ -n "$NODE_NAME" ]]; then
    [[ "$NODE_NAME" =~ ^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$ ]] || {
        echo "ERREUR : --node-name '$NODE_NAME' invalide." >&2
        echo "  Regex attendue : ^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$  (ex. pve2-docker)" >&2
        exit 1
    }
fi
[[ "$SWAP_PERCENT" =~ ^[0-9]+$ ]] && [[ "$SWAP_PERCENT" -le 100 ]] || {
    echo "ERREUR : --swap '$SWAP_PERCENT' invalide — entier 0..100 (%% de la RAM)." >&2
    exit 1
}
if [[ -n "$PORTAL_URL" || -n "$PORTAL_TOKEN" ]]; then
    [[ -n "$PORTAL_URL" && -n "$PORTAL_TOKEN" && -n "$NODE_NAME" ]] || {
        echo "ERREUR : l'enrôlement exige --portal-url, --portal-token ET --node-name." >&2
        exit 1
    }
fi

# Les commandes d'élévation : sudo pour un utilisateur non-root, rien pour root.
# Recalculé ici (jamais hérité de l'appelant) : le contrat d'entrée est le
# triplet (adresse, user, clé), rien d'autre.
if [[ "$CI_USER" == "root" ]]; then
    SUDO=""
else
    SUDO="sudo"
fi

# Tableau (PAS une chaîne) : avec IFS=$'\n\t' en tête de script, une chaîne
# "-o A -o B" non-quotée n'est PAS découpée sur les espaces et ssh reçoit tout
# en un seul argument ("keyword ... extra arguments at end of line"). Un tableau
# passe chaque option comme argument distinct, indépendamment d'IFS.
# UserKnownHostsFile=/dev/null : ignore known_hosts (VM recréée = nouvelle empreinte).
SSH_OPTS=(
    -o StrictHostKeyChecking=no
    -o UserKnownHostsFile=/dev/null
    -o ConnectTimeout=5
    -o BatchMode=yes
    -o LogLevel=ERROR
    -i "$SSH_PRIVATE_KEY"
)

# Contrat de sortie : sur tout échec, l'étape atteinte part sur stderr — c'est
# ce que l'appelant (script ou portail) journalise pour diagnostiquer.
STAGE="préliminaires"
trap 'echo "ERREUR : échec à l'\''étape ${STAGE}." >&2' ERR
# Un échec dur du ssh de A.10c saute le rm -f en ligne : le trap EXIT couvre ce
# cas (${VAR:+...} : ne référencer le fichier que s'il a été créé, cf. set -u).
HARDEN_TMP=""
trap 'rm -f ${HARDEN_TMP:+"$HARDEN_TMP"}' EXIT

# ─── A.10 — Installer les paquets système requis ─────────────────────────────
STAGE="A.10 (paquets, docker, buildx)"
echo ""
echo "==> A.10 — Installation des paquets (git, openssl, docker)..."

ssh "${SSH_OPTS[@]}" "${CI_USER}@${IP_ADDR}" bash <<REMOTE
set -e
export DEBIAN_FRONTEND=noninteractive
${SUDO} cloud-init status --wait 2>/dev/null || true
# apt-daily et unattended-upgrades peuvent tenir le lock après cloud-init.
# systemctl stop bloque autant que le processus ; on laisse apt gérer ses locks :
#   - update : retry toutes les 5s jusqu'à 300s (lock lists/)
#   - install : DPkg::Lock::Timeout attend jusqu'à 300s (lock dpkg)
_t=0
until ${SUDO} apt-get update -qq 2>/dev/null; do
    sleep 5; _t=\$(( _t + 5 ))
    [ \$_t -ge 300 ] && { echo "ERREUR: apt-get update en échec après 300s" >&2; exit 1; }
done
# git et openssl : dépôts Debian standard (toujours disponibles)
${SUDO} apt-get -o "DPkg::Lock::Timeout=300" install -y --no-install-recommends git openssl
# Docker CE + compose v2 : script officiel (docker-compose-plugin absent des dépôts Debian)
curl -fsSL https://get.docker.com | ${SUDO} sh
${SUDO} systemctl enable --now docker
# DevPod SSH provider pilote Docker en tant qu'utilisateur non-root :
# l'utilisateur doit être dans le groupe docker pour éviter l'erreur "rerun as root".
${SUDO} usermod -aG docker "${CI_USER}"
# Builder buildx docker-container — indispensable pour éviter l'erreur buildkit
# "only one connection allowed" du driver docker intégré (une seule session buildkit
# simultanée). sudo -u lit /etc/group au moment de l'appel, donc le nouveau groupe
# est actif immédiatement sans besoin de rouvrir la session SSH.
if ! ${SUDO} -u "${CI_USER}" docker buildx inspect devpod-builder &>/dev/null 2>&1; then
    ${SUDO} -u "${CI_USER}" docker buildx create \
        --name devpod-builder \
        --driver docker-container \
        --bootstrap \
        --use
else
    ${SUDO} -u "${CI_USER}" docker buildx use devpod-builder
fi
REMOTE

echo "    Paquets installés (git, openssl, docker CE + compose v2)."
echo "    Utilisateur '${CI_USER}' ajouté au groupe docker."
echo "    Builder 'devpod-builder' (docker-container) configuré."

# ─── A.10b — Swapfile d'urgence (enabler 74ad4fdf) ───────────────────────────
# Posé ici (provisioning SSH) plutôt que via du user-data cloud-init : sur
# Proxmox, `cicustom user=` REMPLACE tout le user-data généré et ferait sauter
# --sshkeys/--cipassword ; et un provider cloud n'offre pas toujours la main
# sur le user-data. Idempotent : re-run du script → aucune duplication.
if [[ "$SWAP_PERCENT" -gt 0 ]]; then
    STAGE="A.10b (swapfile)"
    # La taille se calcule sur la RAM effective de la machine (MemTotal), pas sur
    # une valeur passée par l'appelant : ce script ne sait pas comment la machine
    # a été créée, et c'est la RAM réelle qui dimensionne l'airbag.
    MEM_TOTAL_MB=$(ssh -n "${SSH_OPTS[@]}" "${CI_USER}@${IP_ADDR}" \
        "awk '/^MemTotal/ {print int(\$2/1024)}' /proc/meminfo")
    SWAP_MB=$(( MEM_TOTAL_MB * SWAP_PERCENT / 100 ))
    [[ "$SWAP_MB" -lt "$SWAP_MIN_MB" ]] && SWAP_MB="$SWAP_MIN_MB"
    [[ "$SWAP_MB" -gt "$SWAP_MAX_MB" ]] && SWAP_MB="$SWAP_MAX_MB"

    echo ""
    echo "==> A.10b — Swapfile ${SWAP_MB} Mo (${SWAP_PERCENT}% RAM, swappiness ${SWAPPINESS})..."

    ssh "${SSH_OPTS[@]}" "${CI_USER}@${IP_ADDR}" bash <<REMOTE
set -e
if ! ${SUDO} test -f /swapfile; then
    # fallocate est instantané ; dd en secours (systèmes de fichiers sans support)
    ${SUDO} fallocate -l ${SWAP_MB}M /swapfile 2>/dev/null \
        || ${SUDO} dd if=/dev/zero of=/swapfile bs=1M count=${SWAP_MB} status=none
    ${SUDO} chmod 600 /swapfile
    ${SUDO} mkswap /swapfile > /dev/null
fi
# Activer si pas déjà actif (re-run) ; fstab pour la persistance au reboot
${SUDO} swapon --show=NAME --noheadings 2>/dev/null | grep -qx /swapfile \
    || ${SUDO} swapon /swapfile
grep -q '^/swapfile' /etc/fstab \
    || echo '/swapfile none swap sw 0 0' | ${SUDO} tee -a /etc/fstab > /dev/null
# Swap d'URGENCE : inerte tant que la RAM suffit (défaut 60 = swap proactif qui
# fait ramer les conteneurs actifs d'un host Docker)
printf 'vm.swappiness=${SWAPPINESS}\n' | ${SUDO} tee /etc/sysctl.d/99-swappiness.conf > /dev/null
${SUDO} sysctl -q -p /etc/sysctl.d/99-swappiness.conf
REMOTE

    echo "    Swapfile actif et persistant (fstab + sysctl.d)."
fi

# ─── A.10c — Résilience réseau (enabler 59864c37) ────────────────────────────
# networkd protégé de l'OOM killer, KeepConfiguration=yes (un échec DHCP ne
# flush plus l'adresse — incident du 24/07), timer de reprise automatique.
# Script mutualisé avec le durcissement des VM existantes (harden-networkd.sh).
STAGE="A.10c (résilience réseau)"
HARDEN_URL="https://raw.githubusercontent.com/gaelgael5/devpod-ui/refs/heads/dev/scripts/harden-networkd.sh"
echo ""
echo "==> A.10c — Résilience réseau (networkd)..."
HARDEN_TMP=$(mktemp /tmp/harden-networkd-XXXXXX.sh)
if curl -fsSL "$HARDEN_URL" -o "$HARDEN_TMP" 2>/dev/null; then
    if ssh "${SSH_OPTS[@]}" "${CI_USER}@${IP_ADDR}" "${SUDO} bash -s" < "$HARDEN_TMP"; then
        echo "    Résilience réseau appliquée (OOM shield + KeepConfiguration + timer)."
    else
        echo "AVERTISSEMENT : harden-networkd.sh a échoué sur la VM — à rejouer à la main." >&2
    fi
else
    echo "AVERTISSEMENT : $HARDEN_URL introuvable — étape A.10c ignorée." >&2
fi
rm -f "$HARDEN_TMP"

# ─── A.10d — Accès à /dev/kvm (enabler ab83a2e9) ─────────────────────────────
# Le périphérique appartient à un groupe, et sans y être l'utilisateur le voit
# sans pouvoir s'en servir : l'émulateur Android échoue alors sur « pas d'accès
# à /dev/kvm », après avoir été installé.
#
# La condition est la PRÉSENCE de /dev/kvm dans l'invité — pas le modèle CPU
# demandé à la création, qui est une notion d'hyperviseur : elle vaut donc sur
# n'importe quel provider.
#
# Le nom du groupe n'est PAS codé en dur. Il est créé par udev à l'apparition
# du périphérique et varie selon la distribution : on lit celui du fichier.
STAGE="A.10d (/dev/kvm)"
echo ""
echo "==> A.10d — Accès à /dev/kvm pour ${CI_USER}..."

ssh "${SSH_OPTS[@]}" "${CI_USER}@${IP_ADDR}" bash <<REMOTE
set -e
if [ ! -e /dev/kvm ]; then
    # L'hyperviseur n'expose pas les extensions de virtualisation à cette
    # machine : rien à donner, et surtout pas d'échec de plus.
    echo "    /dev/kvm absent — virtualisation non exposée à cette machine, rien à donner."
    exit 0
fi
GROUPE=\$(stat -c %G /dev/kvm)
if id -nG ${CI_USER} | tr ' ' '\n' | grep -qx "\$GROUPE"; then
    echo "    ${CI_USER} est déjà dans le groupe \$GROUPE."
else
    ${SUDO} usermod -aG "\$GROUPE" ${CI_USER}
    echo "    ${CI_USER} ajouté au groupe \$GROUPE."
fi
REMOTE

if [[ "$CPU_TYPE" == "host" ]]; then
    echo "    (--cpu-type host : si /dev/kvm était absent, activer le nesting côté hyperviseur.)"
fi
echo "    Effectif au prochain démarrage de session (déjà le cas pour une VM neuve)."

# ─── A.11 — Vérifier et finaliser le hostname ────────────────────────────────
if [[ -n "$NODE_NAME" ]]; then
    STAGE="A.11 (hostname)"
    echo ""
    echo "==> A.11 — Vérification du hostname et de /etc/hosts..."

    ssh "${SSH_OPTS[@]}" "${CI_USER}@${IP_ADDR}" bash <<REMOTE
set -e
EXPECTED="$NODE_NAME"
SUDO="$SUDO"

# Vérifier le hostname courant (cloud-init le fixe depuis le nom de la VM)
CURRENT=\$(hostname)
if [[ "\$CURRENT" != "\$EXPECTED" ]]; then
    echo "    Correction du hostname : \$CURRENT -> \$EXPECTED"
    \$SUDO hostnamectl set-hostname "\$EXPECTED"
fi

# Garantir la présence de 127.0.1.1 dans /etc/hosts (évite les warnings sudo)
if ! grep -q "127.0.1.1" /etc/hosts 2>/dev/null; then
    echo "127.0.1.1	\$EXPECTED" | \$SUDO tee -a /etc/hosts > /dev/null
elif ! grep "127.0.1.1" /etc/hosts | grep -q "\$EXPECTED"; then
    \$SUDO sed -i "s/^127.0.1.1.*/127.0.1.1\t\$EXPECTED/" /etc/hosts
fi

echo "    Hostname : \$(hostname)"
REMOTE

    echo "    Hostname vérifié."
fi

# ─── A.12 — Enrôlement dans le portail (optionnel) ───────────────────────────
if [[ -n "$PORTAL_URL" && -n "$PORTAL_TOKEN" ]]; then
    STAGE="A.12 (enrôlement portail)"
    echo ""
    echo "==> A.12 — Enrôlement du nœud dans le portail..."
    ssh "${SSH_OPTS[@]}" "${CI_USER}@${IP_ADDR}" bash <<REMOTE
set -e
${SUDO} bash /opt/workspace-portal/scripts/install-node.sh \
    --portal "${PORTAL_URL}" \
    --token "${PORTAL_TOKEN}" \
    --node-name "${NODE_NAME}" \
    --address "${IP_ADDR}"
REMOTE
    echo "    Nœud enrôlé dans le portail."
fi

echo ""
echo "    Configuration du nœud terminée (${CI_USER}@${IP_ADDR})."
