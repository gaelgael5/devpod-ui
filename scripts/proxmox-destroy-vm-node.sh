#!/usr/bin/env bash
# proxmox-destroy-vm-node.sh — Arrête et supprime une VM Proxmox par son VMID.
# À exécuter en root sur le host PVE, pas dans une VM.
#
# Usage :
#   bash proxmox-destroy-vm-node.sh <VMID> [OPTIONS]
#
# Arguments obligatoires :
#   <VMID>            VMID de la VM à supprimer (entier positif)
#
# Options :
#   --force           Supprimer sans demande de confirmation
#   --purge           Supprimer aussi de la conf HA / réplication Proxmox

set -euo pipefail
IFS=$'\n\t'

# ─── Arguments positionnels ───────────────────────────────────────────────────
if [[ $# -lt 1 ]]; then
    echo "ERREUR : VMID manquant." >&2
    echo "Usage : bash $0 <VMID> [--force] [--purge]" >&2
    exit 1
fi
VMID="$1"
shift

# ─── Options facultatives ─────────────────────────────────────────────────────
FORCE=false
PURGE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --force)  FORCE=true;  shift ;;
        --purge)  PURGE=true;  shift ;;
        *)
            echo "ERREUR : option inconnue : $1" >&2
            echo "Options supportées : --force, --purge" >&2
            exit 1
            ;;
    esac
done

# ─── Prérequis système ────────────────────────────────────────────────────────
for cmd in qm; do
    command -v "$cmd" &>/dev/null || {
        echo "ERREUR : '$cmd' introuvable — exécuter en root sur un host Proxmox VE." >&2
        exit 1
    }
done

# ─── Validation du VMID ───────────────────────────────────────────────────────
[[ "$VMID" =~ ^[0-9]+$ ]] || {
    echo "ERREUR : VMID invalide : '$VMID' — doit être un entier positif." >&2
    exit 1
}

# ─── Vérifier que la VM existe ───────────────────────────────────────────────
qm list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$VMID" || {
    echo "ERREUR : aucune VM avec le VMID $VMID sur ce host." >&2
    echo "  Lister les VM : qm list" >&2
    exit 1
}

VM_NAME=$(qm config "$VMID" 2>/dev/null | grep '^name:' | awk '{print $2}')
VM_STATUS=$(qm status "$VMID" 2>/dev/null | awk '{print $2}')

echo ""
echo "  VM ciblée : ${VM_NAME:-<sans nom>}  (VMID $VMID)  — état actuel : $VM_STATUS"
echo ""

# ─── Confirmation interactive ─────────────────────────────────────────────────
if [[ "$FORCE" == "false" ]]; then
    printf "  Supprimer définitivement cette VM ? [oui/NON] : "
    read -r CONFIRM
    [[ "$CONFIRM" == "oui" ]] || {
        echo "  Annulé."
        exit 0
    }
fi

# ─── Arrêt de la VM ───────────────────────────────────────────────────────────
echo ""
echo "==> Arrêt de la VM VMID $VMID..."

if [[ "$VM_STATUS" == "running" ]]; then
    qm stop "$VMID"
    echo "    Arrêt demandé — attente de l'extinction (max 60s)..."
    ELAPSED=0
    until [[ "$(qm status "$VMID" 2>/dev/null | awk '{print $2}')" == "stopped" ]]; do
        if [[ $ELAPSED -ge 60 ]]; then
            echo "    Timeout — forçage par kill du processus QEMU..."
            QEMU_PID=$(pgrep -f "qemu-system.*\-id ${VMID}[^0-9]" 2>/dev/null || true)
            if [[ -n "$QEMU_PID" ]]; then
                kill -9 "$QEMU_PID" || true
                sleep 2
            else
                echo "    AVERTISSEMENT : processus QEMU introuvable pour VMID $VMID." >&2
            fi
            break
        fi
        printf "\r    %3ds — en attente de l'arrêt..." "$ELAPSED"
        sleep 3
        ELAPSED=$(( ELAPSED + 3 ))
    done
    echo ""
    echo "    VM arrêtée."
else
    echo "    VM déjà arrêtée (état : $VM_STATUS)."
fi

# ─── Suppression de la VM et de ses disques ──────────────────────────────────
echo ""
echo "==> Suppression de la VM et de ses disques (VMID $VMID)..."

DESTROY_ARGS=("$VMID" --destroy-unreferenced-disks 1)
[[ "$PURGE" == "true" ]] && DESTROY_ARGS+=(--purge 1)

qm destroy "${DESTROY_ARGS[@]}"

echo "    VM $VMID supprimée."

# ─── Résumé ───────────────────────────────────────────────────────────────────
echo ""
echo "======================================================"
echo "  Supprimée : ${VM_NAME:-<sans nom>}  (VMID $VMID)"
echo "======================================================"
echo ""
