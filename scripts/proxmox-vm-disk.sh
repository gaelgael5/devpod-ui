#!/usr/bin/env bash
# proxmox-vm-disk.sh — Agrandit le disque d'une VM Proxmox d'un delta.
# À exécuter en root sur le host PVE, pas dans une VM.
#
# Usage :
#   bash proxmox-vm-disk.sh <VMID> --delta <+NG> [OPTIONS]
#
# Arguments obligatoires :
#   <VMID>            VMID de la VM à ajuster (entier positif)
#   --delta <+NG>     Ajout, signe + obligatoire (ex. +10G, +512M)
#
# Options :
#   --disk <nom>      Disque à agrandir (ex. scsi0). Défaut : disque de boot
#                     détecté dans la config.
#   --no-guest        Ne pas étendre la partition et le système de fichiers dans
#                     l'invité — on se contente d'agrandir le disque virtuel.
#
# RÉDUCTION IMPOSSIBLE. La documentation Proxmox est explicite :
#   « Shrinking disk size is not supported. »
# `qm disk resize` refuse un delta négatif. Réduire un disque suppose de réduire
# d'abord le système de fichiers puis le volume, hors ligne, et toute erreur
# d'ordre détruit les données. Ce script ne le tente pas.

set -euo pipefail
IFS=$'\n\t'

DELTA=""
DISQUE=""
GUEST=true

if [[ $# -lt 1 ]]; then
    echo "ERREUR : VMID manquant." >&2
    echo "Usage : bash $0 <VMID> --delta <+NG> [--disk scsi0] [--no-guest]" >&2
    exit 1
fi
VMID="$1"
shift

while [[ $# -gt 0 ]]; do
    case "$1" in
        --delta)    DELTA="$2";  shift 2 ;;
        --disk)     DISQUE="$2"; shift 2 ;;
        --no-guest) GUEST=false; shift ;;
        *)
            echo "ERREUR : option inconnue : $1" >&2
            echo "Options supportées : --delta, --disk, --no-guest" >&2
            exit 1
            ;;
    esac
done

command -v qm &>/dev/null || {
    echo "ERREUR : 'qm' introuvable — exécuter en root sur un host Proxmox VE." >&2
    exit 1
}

[[ "$VMID" =~ ^[0-9]+$ ]] || {
    echo "ERREUR : VMID invalide : '$VMID' — doit être un entier positif." >&2
    exit 1
}

# Le signe est ce qui distingue un agrandissement d'une taille absolue : sans
# lui, `qm disk resize 105 scsi0 10G` RAMÈNERAIT le disque à 10 Go.
if [[ "$DELTA" == -* ]]; then
    echo "ERREUR : réduction demandée (${DELTA}) — Proxmox ne sait pas rétrécir un disque." >&2
    echo "  « Shrinking disk size is not supported » (doc qm)." >&2
    echo "  Il faut réduire le système de fichiers puis le volume hors ligne," >&2
    echo "  opération destructrice en cas d'erreur d'ordre. Non couvert ici." >&2
    exit 1
fi
[[ "$DELTA" =~ ^\+[0-9]+[MGT]$ ]] || {
    echo "ERREUR : delta invalide : '${DELTA}' — attendu +<entier>[M|G|T] (ex. +10G)." >&2
    exit 1
}

qm list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$VMID" || {
    echo "ERREUR : aucune VM avec le VMID $VMID sur ce host." >&2
    echo "  Lister les VM : qm list" >&2
    exit 1
}

CONF="$(qm config "$VMID")"

# ─── Disque cible ────────────────────────────────────────────────────────────
# `bootdisk` n'existe plus dans les configs récentes (remplacé par `boot: order=`).
# On lit les deux, et à défaut on prend le premier disque non-cdrom déclaré.
if [[ -z "$DISQUE" ]]; then
    DISQUE="$(printf '%s\n' "$CONF" | awk -F: '/^bootdisk:/ {gsub(/ /,"",$2); print $2; exit}')"
fi
if [[ -z "$DISQUE" ]]; then
    DISQUE="$(printf '%s\n' "$CONF" | sed -n 's/^boot:.*order=\([^,;]*\).*/\1/p' \
              | tr ';' '\n' | head -n1)"
fi
if [[ -z "$DISQUE" ]]; then
    DISQUE="$(printf '%s\n' "$CONF" \
              | grep -E '^(scsi|virtio|sata|ide)[0-9]+:' \
              | grep -v 'media=cdrom' \
              | head -n1 | cut -d: -f1)"
fi
[[ -n "$DISQUE" ]] || {
    echo "ERREUR : aucun disque trouvé dans la config de la VM $VMID." >&2
    echo "  Préciser lequel :  --disk scsi0" >&2
    exit 1
}
printf '%s\n' "$CONF" | grep -qE "^${DISQUE}:" || {
    echo "ERREUR : le disque '${DISQUE}' n'existe pas sur la VM $VMID." >&2
    echo "  Disques déclarés :" >&2
    printf '%s\n' "$CONF" | grep -E '^(scsi|virtio|sata|ide)[0-9]+:' | sed 's/^/    /' >&2
    exit 1
}

echo "==> VM $VMID — agrandissement de ${DISQUE} de ${DELTA}"
printf '%s\n' "$CONF" | grep -E "^${DISQUE}:" | sed 's/^/    avant : /'

qm disk resize "$VMID" "$DISQUE" "$DELTA"

qm config "$VMID" | grep -E "^${DISQUE}:" | sed 's/^/    après : /'

# ─── Côté invité ─────────────────────────────────────────────────────────────
# Agrandir le disque virtuel ne fait rien voir de plus à l'invité : la table de
# partitions et le système de fichiers gardent leur taille. Sans cette étape,
# l'espace ajouté reste invisible et l'action semble n'avoir servi à rien.
if [[ "$GUEST" == false ]]; then
    echo "==> Extension invité ignorée (--no-guest)."
    exit 0
fi

if ! qm agent "$VMID" ping &>/dev/null; then
    echo "==> AVERTISSEMENT : agent invité injoignable — l'espace ajouté n'est pas"
    echo "    encore visible dans la VM. Depuis la VM, une fois démarrée :"
    echo "      sudo growpart /dev/sda 1 && sudo resize2fs /dev/sda1"
    echo "    (adapter le périphérique : lsblk)"
    exit 0
fi

echo "==> Extension de la partition et du système de fichiers dans l'invité..."
# `|| true` : on ne fait pas échouer l'action pour ça. Le disque EST agrandi ;
# l'extension invité se rejoue à la main, alors qu'un exit non nul ferait croire
# que le redimensionnement n'a pas eu lieu.
if qm guest exec "$VMID" -- /bin/sh -c \
      'growpart /dev/sda 1 && resize2fs /dev/sda1' 2>&1 | sed 's/^/    /'; then
    echo "==> Espace disponible dans la VM."
else
    echo "==> AVERTISSEMENT : extension invité échouée — le disque virtuel est bien"
    echo "    agrandi. À rejouer dans la VM :"
    echo "      sudo growpart /dev/sda 1 && sudo resize2fs /dev/sda1"
fi
