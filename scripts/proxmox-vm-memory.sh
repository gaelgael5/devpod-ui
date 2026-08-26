#!/usr/bin/env bash
# proxmox-vm-memory.sh — Ajuste la mémoire d'une VM Proxmox d'un delta.
# À exécuter en root sur le host PVE, pas dans une VM.
#
# Usage :
#   bash proxmox-vm-memory.sh <VMID> --delta <±MO> [OPTIONS]
#
# Arguments obligatoires :
#   <VMID>            VMID de la VM à ajuster (entier positif)
#   --delta <±MO>     Variation en mébioctets, signée (ex. +1024, -1024)
#
# Options :
#   --min <MO>        Plancher (défaut : 1024). En dessous, la VM ne boote plus
#                     ou se fait tuer par l'OOM killer : on refuse plutôt.
#   --max <MO>        Plafond (défaut : 65536). Garde-fou contre un +1024 répété
#                     par erreur jusqu'à épuiser la RAM de l'hôte.
#
# La modification prend effet au PROCHAIN DÉMARRAGE de la VM (arrêt/démarrage
# complet — un `reboot` invité ne rejoue pas la définition QEMU), sauf si le
# hotplug mémoire est actif sur cette VM.

set -euo pipefail
IFS=$'\n\t'

MIN_MO=1024
MAX_MO=65536
DELTA=""

if [[ $# -lt 1 ]]; then
    echo "ERREUR : VMID manquant." >&2
    echo "Usage : bash $0 <VMID> --delta <±MO> [--min MO] [--max MO]" >&2
    exit 1
fi
VMID="$1"
shift

while [[ $# -gt 0 ]]; do
    case "$1" in
        --delta) DELTA="$2";  shift 2 ;;
        --min)   MIN_MO="$2"; shift 2 ;;
        --max)   MAX_MO="$2"; shift 2 ;;
        *)
            echo "ERREUR : option inconnue : $1" >&2
            echo "Options supportées : --delta, --min, --max" >&2
            exit 1
            ;;
    esac
done

# ─── Prérequis système ────────────────────────────────────────────────────────
command -v qm &>/dev/null || {
    echo "ERREUR : 'qm' introuvable — exécuter en root sur un host Proxmox VE." >&2
    exit 1
}

# ─── Validation des entrées ──────────────────────────────────────────────────
[[ "$VMID" =~ ^[0-9]+$ ]] || {
    echo "ERREUR : VMID invalide : '$VMID' — doit être un entier positif." >&2
    exit 1
}
[[ "$DELTA" =~ ^[+-][0-9]+$ ]] || {
    echo "ERREUR : delta invalide : '${DELTA}' — attendu ±entier en Mo (ex. +1024)." >&2
    exit 1
}
[[ "$MIN_MO" =~ ^[0-9]+$ && "$MAX_MO" =~ ^[0-9]+$ ]] || {
    echo "ERREUR : --min et --max doivent être des entiers." >&2
    exit 1
}

qm list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$VMID" || {
    echo "ERREUR : aucune VM avec le VMID $VMID sur ce host." >&2
    echo "  Lister les VM : qm list" >&2
    exit 1
}

# ─── Mémoire actuelle ────────────────────────────────────────────────────────
# `qm config` rend `memory: 8192` ; les versions récentes savent aussi écrire une
# chaîne de propriétés (`memory: current=8192`). On extrait le premier entier des
# deux formes plutôt que de parier sur l'une.
CONF="$(qm config "$VMID")"
ACTUEL="$(printf '%s\n' "$CONF" | awk -F: '/^memory:/ {print $2; exit}' \
          | grep -oE '[0-9]+' | head -n1 || true)"
[[ -n "$ACTUEL" ]] || {
    echo "ERREUR : mémoire actuelle illisible dans la config de la VM $VMID." >&2
    echo "  Vérifier :  qm config $VMID | grep memory" >&2
    exit 1
}

NOUVEAU=$(( ACTUEL + DELTA ))

echo "==> VM $VMID — mémoire : ${ACTUEL} Mo ${DELTA} Mo = ${NOUVEAU} Mo"

if (( NOUVEAU < MIN_MO )); then
    echo "ERREUR : ${NOUVEAU} Mo est sous le plancher de ${MIN_MO} Mo — refusé." >&2
    echo "  Une VM sous ce seuil ne boote pas ou se fait tuer par l'OOM killer." >&2
    exit 1
fi
if (( NOUVEAU > MAX_MO )); then
    echo "ERREUR : ${NOUVEAU} Mo dépasse le plafond de ${MAX_MO} Mo — refusé." >&2
    echo "  Relever --max si c'est volontaire." >&2
    exit 1
fi

# ─── Ballon ──────────────────────────────────────────────────────────────────
# Proxmox exige balloon <= memory. Un ballon resté au-dessus de la nouvelle
# valeur ferait échouer `qm set` : on le rabat, sauf s'il vaut 0 (ballooning
# désactivé, valeur sentinelle à ne pas toucher).
BALLOON="$(printf '%s\n' "$CONF" | awk -F: '/^balloon:/ {print $2; exit}' \
           | grep -oE '[0-9]+' | head -n1 || true)"
if [[ -n "$BALLOON" && "$BALLOON" != "0" ]] && (( BALLOON > NOUVEAU )); then
    echo "    Ballon ramené de ${BALLOON} Mo à ${NOUVEAU} Mo (balloon <= memory)."
    qm set "$VMID" --balloon "$NOUVEAU" >/dev/null
fi

qm set "$VMID" --memory "$NOUVEAU"

echo "==> Mémoire de la VM $VMID portée à ${NOUVEAU} Mo."
echo "    Effectif au prochain ARRÊT/DÉMARRAGE de la VM (un reboot invité ne"
echo "    rejoue pas la définition QEMU), sauf hotplug mémoire actif."
