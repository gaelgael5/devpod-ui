#!/usr/bin/env bash
# create-vm-generic.sh — Crée un template VM Debian 12 cloud-init sur Proxmox VE.
# À exécuter en root sur le host PVE, pas dans une VM.
#
# Usage :
#   bash create-vm-generic.sh <VMID> [OPTIONS]
#   curl -sSL https://raw.githubusercontent.com/gaelgael5/devpod-ui/refs/heads/main/scripts/create-vm-generic.sh \
#     | bash -s -- <VMID> [OPTIONS]
#
# Arguments :
#   <VMID>            VMID du template à créer (obligatoire, entier positif libre)
#
# Options :
#   --name NOM        Nom du template dans Proxmox   (défaut : debian12-template)
#   --storage NOM     Stockage Proxmox cible          (défaut : auto-détecté)
#   --bridge NOM      Bridge réseau de la VM          (défaut : vmbr0)
#   --cores N         Nombre de vCPU du template      (défaut : 2)
#   --memory N        RAM en Mo du template           (défaut : 2048)
#
# Résultat : un template Proxmox cloud-init prêt à être cloné (Chemin A).
#   Cloner ensuite : qm clone <VMID> <NEW_VMID> --name <nom-noeud> --full
#   Puis suivre : documentations/fr/preparation-vm-noeud-docker.md

set -euo pipefail
IFS=$'\n\t'

# ─── Valeurs par défaut ────────────────────────────────────────────────────────
TEMPLATE_NAME="debian12-template"
STORAGE=""          # auto-détecté à l'étape prérequis
BRIDGE="vmbr0"
CORES=2
MEMORY=2048
# Les binaires compilés avec Bun (ex. claude) exigent AVX ; kvm64 (défaut Proxmox) masque AVX.
# x86-64-v3 expose AVX/AVX2/FMA, est supporté par les deux nœuds du cluster (Haswell + Raptor Lake),
# et reste live-migratable entre eux — contrairement à --cpu host qui épingle au modèle exact.
CPU_TYPE="x86-64-v3"

DEBIAN_CODENAME="bookworm"
DEBIAN_VERSION="12"
ARCH="amd64"
IMAGE_NAME="debian-${DEBIAN_VERSION}-genericcloud-${ARCH}.qcow2"
IMAGE_BASE_URL="https://cloud.debian.org/images/cloud/${DEBIAN_CODENAME}/latest"
IMAGE_URL="${IMAGE_BASE_URL}/${IMAGE_NAME}"
CHECKSUM_URL="${IMAGE_BASE_URL}/SHA512SUMS"

# ─── VMID (1er argument, obligatoire) ─────────────────────────────────────────
if [[ $# -lt 1 ]]; then
    echo "ERREUR : VMID manquant." >&2
    echo "Usage : bash $0 <VMID> [--name NOM] [--storage NOM] [--bridge NOM] [--cores N] [--memory N]" >&2
    exit 1
fi
VMID="$1"
shift

# ─── Options facultatives ─────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --name)    TEMPLATE_NAME="$2"; shift 2 ;;
        --storage) STORAGE="$2";       shift 2 ;;
        --bridge)  BRIDGE="$2";        shift 2 ;;
        --cores)   CORES="$2";         shift 2 ;;
        --memory)  MEMORY="$2";        shift 2 ;;
        --cpu)     CPU_TYPE="$2";      shift 2 ;;
        *)
            echo "ERREUR : option inconnue : $1" >&2
            echo "Options supportées : --name, --storage, --bridge, --cores, --memory, --cpu" >&2
            exit 1
            ;;
    esac
done

# ─── Prérequis ────────────────────────────────────────────────────────────────
echo "==> Vérification des prérequis..."

# Ce script doit tourner sur un host Proxmox VE
for cmd in qm pvesm; do
    command -v "$cmd" &>/dev/null || {
        echo "ERREUR : '$cmd' introuvable — ce script doit être exécuté en root sur un host Proxmox VE." >&2
        exit 1
    }
done

for cmd in wget sha512sum; do
    command -v "$cmd" &>/dev/null || {
        echo "ERREUR : '$cmd' introuvable. Installer : apt-get install -y wget coreutils" >&2
        exit 1
    }
done

# Valider que le VMID est un entier positif
[[ "$VMID" =~ ^[0-9]+$ ]] || {
    echo "ERREUR : VMID invalide : '$VMID' — doit être un entier positif (ex. 9000)." >&2
    exit 1
}

# Vérifier que le VMID n'est pas utilisé par une VM existante
if qm list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$VMID"; then
    echo "ERREUR : VMID $VMID est déjà utilisé par une VM ou un template." >&2
    echo "  Lister les VMID occupés : qm list" >&2
    echo "  Supprimer si nécessaire : qm destroy $VMID" >&2
    exit 1
fi

# Vérifier que le VMID n'est pas utilisé par un conteneur LXC
if pct list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$VMID"; then
    echo "ERREUR : VMID $VMID est déjà utilisé par un conteneur LXC." >&2
    echo "  Lister les conteneurs LXC : pct list" >&2
    echo "  Supprimer si nécessaire : pct destroy $VMID" >&2
    exit 1
fi

echo "    VMID $VMID : libre (aucune VM ni LXC)"

# Auto-détection du stockage si non précisé
if [[ -z "$STORAGE" ]]; then
    # Préférence : local-lvm (LVM-thin, performant) > local-zfs > local (répertoire)
    for candidate in local-lvm local-zfs local; do
        if pvesm status 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$candidate"; then
            STORAGE="$candidate"
            echo "    Stockage auto-détecté : $STORAGE"
            break
        fi
    done
    [[ -n "$STORAGE" ]] || {
        echo "ERREUR : aucun stockage utilisable détecté." >&2
        echo "  Préciser manuellement : --storage NOM" >&2
        echo "  Stockages disponibles : $(pvesm status 2>/dev/null | awk 'NR>1 {print $1}' | tr '\n' ' ')" >&2
        exit 1
    }
else
    pvesm status 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$STORAGE" || {
        echo "ERREUR : stockage '$STORAGE' introuvable." >&2
        echo "  Stockages disponibles : $(pvesm status 2>/dev/null | awk 'NR>1 {print $1}' | tr '\n' ' ')" >&2
        exit 1
    }
    echo "    Stockage : $STORAGE"
fi

echo ""
echo "==> Paramètres retenus :"
echo "    VMID          : $VMID"
echo "    Nom template  : $TEMPLATE_NAME"
echo "    Stockage      : $STORAGE"
echo "    Bridge réseau : $BRIDGE"
echo "    vCPU / RAM    : ${CORES} cores / ${MEMORY} Mo"
echo "    Modèle CPU    : $CPU_TYPE"
echo "    Image OS      : $IMAGE_NAME"
echo ""

# ─── Répertoire temporaire — nettoyé automatiquement à la sortie ──────────────
TMP_DIR=$(mktemp -d /tmp/create-vm-XXXXXX)
trap 'rm -rf "$TMP_DIR"' EXIT

# ─── Téléchargement de l'image cloud ─────────────────────────────────────────
echo "==> Téléchargement de l'image cloud Debian ${DEBIAN_VERSION}..."
echo "    $IMAGE_URL"

IMAGE_FILE="${TMP_DIR}/${IMAGE_NAME}"
CHECKSUM_FILE="${TMP_DIR}/SHA512SUMS"

wget --quiet --show-progress -O "$IMAGE_FILE"    "$IMAGE_URL"    || {
    echo "ERREUR : téléchargement de l'image échoué." >&2
    exit 1
}
wget --quiet                  -O "$CHECKSUM_FILE" "$CHECKSUM_URL" || {
    echo "ERREUR : téléchargement du fichier de sommes échoué." >&2
    exit 1
}

echo "==> Vérification de l'intégrité SHA512..."
# sha512sum résout les chemins depuis le CWD — se placer dans le répertoire temporaire
(
    cd "$TMP_DIR"
    grep "$IMAGE_NAME" SHA512SUMS | sha512sum --check --status
) || {
    echo "ERREUR : somme SHA512 incorrecte — image corrompue ou URL invalide." >&2
    exit 1
}
echo "    Intégrité vérifiée."

# ─── Préconfiguration cloud-init dans l'image ────────────────────────────────
# virt-customize modifie l'image qcow2 sans la démarrer.
# Force le datasource NoCloud (requis pour Proxmox) et active le module set-passwords.
echo ""
echo "==> Préconfiguration cloud-init dans l'image (virt-customize)..."

if ! command -v virt-customize &>/dev/null; then
    echo "    virt-customize introuvable — installation de libguestfs-tools (peut prendre 1 min)..."
    DEBIAN_FRONTEND=noninteractive apt-get install -y libguestfs-tools \
        -o Dpkg::Options::="--force-confold" \
        -o APT::Get::Show-Upgraded=false \
        -qq > /dev/null 2>&1 || true
fi

VIRT_CUSTOMIZE_OK=false
if command -v virt-customize &>/dev/null; then
    if LIBGUESTFS_BACKEND=direct virt-customize -a "$IMAGE_FILE" \
            --run-command 'printf "datasource_list: [NoCloud, None]\n" > /etc/cloud/cloud.cfg.d/99-proxmox.cfg' \
            --run-command 'grep -q "set-passwords" /etc/cloud/cloud.cfg || sed -i "/^cloud_config_modules:/a\\ - set-passwords" /etc/cloud/cloud.cfg' \
            --run-command 'truncate -s 0 /etc/machine-id' \
            --run-command 'rm -f /var/lib/dbus/machine-id && ln -sf /etc/machine-id /var/lib/dbus/machine-id' \
            --run-command 'rm -f /etc/ssh/ssh_host_*' \
            --run-command 'cloud-init clean --logs' \
            --quiet 2>/dev/null; then
        VIRT_CUSTOMIZE_OK=true
        echo "    cloud-init configuré et image scellée (datasource NoCloud + set-passwords, machine-id vidé, clés SSH host supprimées)."
    else
        echo "    AVERTISSEMENT : virt-customize a échoué — cloud-init non préconfiguré." >&2
    fi
else
    echo "    AVERTISSEMENT : libguestfs-tools indisponible — cloud-init non préconfiguré." >&2
fi

# ─── Création de la VM vide ───────────────────────────────────────────────────
echo ""
echo "==> Création de la VM (VMID $VMID)..."

qm create "$VMID" \
    --name    "$TEMPLATE_NAME" \
    --memory  "$MEMORY" \
    --cores   "$CORES" \
    --cpu     "$CPU_TYPE" \
    --net0    "virtio,bridge=${BRIDGE}" \
    --ostype  l26 \
    --machine q35 \
    --serial0 socket \
    --vga     serial0

echo "    VM créée."

# ─── Import du disque cloud dans le stockage ─────────────────────────────────
echo ""
echo "==> Import du disque (opération longue selon le stockage)..."

qm importdisk "$VMID" "$IMAGE_FILE" "$STORAGE" 2>&1

# Récupérer le nom exact du disque importé (apparaît en tant que 'unused0' dans qm config)
DISK=$(qm config "$VMID" | grep '^unused0:' | sed 's/^unused0: *//')
if [[ -z "$DISK" ]]; then
    echo "ERREUR : disque importé non trouvé dans la config de la VM." >&2
    echo "  Vérifier : qm config $VMID" >&2
    exit 1
fi
echo "    Disque importé : $DISK"

# ─── Attacher le disque et configurer le système ─────────────────────────────
echo ""
echo "==> Configuration du disque, cloud-init et démarrage..."

# Attacher comme scsi0 avec contrôleur VirtIO SCSI et TRIM activé
qm set "$VMID" \
    --scsihw virtio-scsi-pci \
    --scsi0  "${DISK},discard=on"

# Lecteur cloud-init sur scsi1 (même contrôleur VirtIO SCSI que scsi0) — détecté comme /dev/sr0
# IMPORTANT : ne pas utiliser ide2 sur Debian 12 genericcloud — le driver AHCI n'est pas chargé
# assez tôt dans l'initramfs et blkid ne voit pas le device cidata (DataSourceNone au lieu de NoCloud).
qm set "$VMID" --scsi1 "${STORAGE}:cloudinit"

# Ordre de démarrage : scsi0 en premier
qm set "$VMID" --boot order=scsi0

echo "    Disque attaché, cloud-init ajouté, ordre de boot configuré."

# ─── Conversion en template ───────────────────────────────────────────────────
echo ""
echo "==> Conversion en template Proxmox..."

qm template "$VMID"

echo "    VMID $VMID converti en template."

# ─── Résumé ───────────────────────────────────────────────────────────────────
echo ""
echo "======================================================"
echo "  Template créé : $TEMPLATE_NAME (VMID $VMID)"
echo "======================================================"
echo ""
if $VIRT_CUSTOMIZE_OK; then
    echo "  ✓ cloud-init configuré et image scellée :"
    echo "     - datasource NoCloud + set-passwords activé"
    echo "     - /etc/machine-id vidé (DUID unique par clone)"
    echo "     - clés SSH host supprimées (régénérées au premier démarrage)"
else
    echo "  ATTENTION : virt-customize n'a pas pu configurer/sceller l'image."
    echo "  RISQUE : les clones auront le même machine-id → conflit DHCP (même IP pour tous)."
    echo "  Installer libguestfs-tools et recréer le template :"
    echo "    apt-get install -y libguestfs-tools"
fi
echo ""
echo "Prochaine étape — créer un nœud Docker depuis ce template :"
echo "  bash clone-vm-node.sh <NEW_VMID> --name <nom> --template $VMID --storage $STORAGE"
echo "  Puis suivre : documentations/fr/preparation-vm-noeud-docker.md (Chemin A)"
echo ""
