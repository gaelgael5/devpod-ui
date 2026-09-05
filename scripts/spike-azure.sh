#!/usr/bin/env bash
# spike-azure.sh — Spike du ticket 3 (épic provisionnement) : éprouver le
# vocabulaire MachineSpec contre Azure, hors portail, puis TOUT détruire.
#
# Monte une VM Debian 12 stock depuis une spec écrite dans le vocabulaire du
# contrat (cpu/memory_mb en DEMANDE, résolus vers le plus petit SKU suffisant),
# la configure avec configure-node.sh NON MODIFIÉ, chronomètre chaque phase,
# et supprime le resource group à la fin (y compris sur échec, sauf --keep).
#
# Prérequis : az cli connecté (`az login`), une souscription active.
# Coût : quelques centimes (VM ~10 min). Rien ne survit au script sauf --keep.
#
# Usage :
#   bash spike-azure.sh [--region francecentral] [--cpu 4] [--memory-mb 8192] \
#                       [--disk-gb 40] [--user debian] [--keep]
#
# Réponses attendues (questions du ticket) :
#   Q1/Q4 : configure-node.sh passe-t-il sur une image stock ?  → verdict affiché
#   Q5    : durées réelles de chaque phase                       → chronomètre
#   Q6    : la VM est-elle joignable sans IP publique ?          → non par défaut,
#           le spike EXPOSE une IP publique pour pouvoir tester — c'est
#           précisément ce qu'on refuse en production (→ ticket 7, tailnet).

set -euo pipefail
IFS=$'\n\t'

REGION="francecentral"
CPU=4
MEMORY_MB=8192
DISK_GB=40
CI_USER="debian"
KEEP=false
NAME="spike-az-01"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --region)    REGION="$2";    shift 2 ;;
        --cpu)       CPU="$2";       shift 2 ;;
        --memory-mb) MEMORY_MB="$2"; shift 2 ;;
        --disk-gb)   DISK_GB="$2";   shift 2 ;;
        --user)      CI_USER="$2";   shift 2 ;;
        --name)      NAME="$2";      shift 2 ;;
        --keep)      KEEP=true;      shift ;;
        *) echo "ERREUR : option inconnue : $1" >&2
           echo "Options : --region --cpu --memory-mb --disk-gb --user --name --keep" >&2
           exit 1 ;;
    esac
done

command -v az >/dev/null || { echo "ERREUR : az cli absent (https://aka.ms/azcli)." >&2; exit 1; }
az account show >/dev/null 2>&1 || { echo "ERREUR : pas de session az — lancer 'az login'." >&2; exit 1; }

# Clé SSH jetable, propre au spike : rien de personnel ne part chez Azure.
WORKDIR=$(mktemp -d /tmp/spike-azure-XXXXXX)
ssh-keygen -t ed25519 -N '' -q -f "$WORKDIR/key"
SSH_PUBKEY="$WORKDIR/key.pub"
SSH_PRIVKEY="$WORKDIR/key"

RG="rg-${NAME}"
T0=$(date +%s)
phase() { printf '\n==> [%4ss] %s\n' "$(( $(date +%s) - T0 ))" "$*"; }

cleanup() {
    local rc=$?
    if [[ "$KEEP" == "true" ]]; then
        echo ""
        echo "--keep : le resource group ${RG} est CONSERVÉ — il FACTURE tant qu'il existe."
        echo "Destruction manuelle : az group delete --name ${RG} --yes --no-wait"
    else
        phase "Destruction du resource group ${RG} (cascade : VM, NIC, IP, NSG, disque, vnet)..."
        az group delete --name "$RG" --yes --no-wait 2>/dev/null || true
        echo "    Suppression lancée (asynchrone côté Azure). Vérifier : az group exists --name ${RG}"
    fi
    rm -rf "$WORKDIR"
    exit $rc
}
trap cleanup EXIT

# ─── Résolution demande → SKU (le cœur du tranchage du ticket 3) ─────────────
# Famille déclarée ici en dur (Dads_v5) — dans le portail, c'est une propriété
# de l'hyperviseur. Plus petit SKU dont cpu ET mémoire couvrent la demande.
phase "Résolution de la demande (${CPU} vCPU / ${MEMORY_MB} Mo) vers un SKU ${REGION}..."
INSTANCE_SIZE=$(az vm list-sizes --location "$REGION" -o tsv \
        --query "[?starts_with(name, 'Standard_D') && contains(name, 'ads_v5')].[name, numberOfCores, memoryInMB]" \
    | awk -v cpu="$CPU" -v mem="$MEMORY_MB" \
        '$2 >= cpu && $3 >= mem { if (best == "" || $2 < bc || ($2 == bc && $3 < bm)) { best=$1; bc=$2; bm=$3 } }
         END { print best }')
[[ -n "$INSTANCE_SIZE" ]] || { echo "ERREUR : aucun SKU Dads_v5 ⩾ demande dans ${REGION}." >&2; exit 1; }
echo "    Demande résolue : ${INSTANCE_SIZE}"

# ─── La spec, dans le vocabulaire du contrat (trace du spike) ────────────────
cat > "$WORKDIR/spec.json" <<SPEC
{
  "name": "${NAME}",
  "cpu": ${CPU}, "memory_mb": ${MEMORY_MB}, "disk_gb": ${DISK_GB},
  "user": "${CI_USER}",
  "ssh_authorized_keys": ["$(cat "$SSH_PUBKEY")"],
  "network": {"mode": "dhcp"},
  "provider": {"type": "azure", "region": "${REGION}", "resource_group": "${RG}",
               "instance_size": "${INSTANCE_SIZE}", "image": "Debian:debian-12:12-gen2:latest"}
}
SPEC
echo "    Spec écrite : $WORKDIR/spec.json"

# ─── Création ─────────────────────────────────────────────────────────────────
phase "Création du resource group ${RG}..."
az group create --name "$RG" --location "$REGION" --output none \
    --tags "portal=spike" "owner=$(az account show --query user.name -o tsv)"

phase "Création de la VM (image Debian 12 stock, IP publique POUR LE SPIKE seulement)..."
az vm create --resource-group "$RG" --name "$NAME" \
    --image "Debian:debian-12:12-gen2:latest" \
    --size "$INSTANCE_SIZE" \
    --os-disk-size-gb "$DISK_GB" \
    --admin-username "$CI_USER" \
    --ssh-key-values "$SSH_PUBKEY" \
    --public-ip-sku Standard \
    --output none

IP_ADDR=$(az vm show -d --resource-group "$RG" --name "$NAME" --query publicIps -o tsv)
[[ -n "$IP_ADDR" ]] || { echo "ERREUR : pas d'IP publique rendue." >&2; exit 1; }
phase "VM créée, IP publique : ${IP_ADDR}"

# ─── Q6 — l'IP privée est-elle joignable sans ça ? ───────────────────────────
PRIVATE_IP=$(az vm show -d --resource-group "$RG" --name "$NAME" --query privateIps -o tsv)
echo "    IP privée : ${PRIVATE_IP} — injoignable hors du vnet : c'est la réponse à Q6."

# ─── Attente SSH (même logique que A.9 : le vrai SSH par clé, pas le port) ───
phase "Attente de SSH sur ${IP_ADDR} (max 300s)..."
SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
          -o ConnectTimeout=5 -o BatchMode=yes -o LogLevel=ERROR -i "$SSH_PRIVKEY")
ELAPSED=0
until ssh -n "${SSH_OPTS[@]}" "${CI_USER}@${IP_ADDR}" "exit 0" 2>/dev/null; do
    [[ $ELAPSED -ge 300 ]] && { echo "ERREUR : SSH indisponible après 300s." >&2; exit 1; }
    sleep 5; ELAPSED=$(( ELAPSED + 5 ))
done
phase "SSH opérationnel."

# ─── Q1/Q4 — configure-node.sh NON MODIFIÉ sur image stock ───────────────────
CONFIGURE_SH="$(dirname "${BASH_SOURCE[0]:-.}")/configure-node.sh"
[[ -f "$CONFIGURE_SH" ]] || {
    echo "ERREUR : configure-node.sh introuvable à côté de ce script." >&2; exit 1; }
phase "configure-node.sh sur la VM (verdict Q1/Q4)..."
if bash "$CONFIGURE_SH" --address "$IP_ADDR" --user "$CI_USER" --key "$SSH_PRIVKEY" \
        --node-name "$NAME" < /dev/null; then
    phase "VERDICT Q1/Q4 : la phase de configuration est PORTABLE — image stock suffisante."
else
    phase "VERDICT Q1/Q4 : ÉCHEC — la raison ci-dessus est ce que le contrat doit exposer."
    exit 1
fi

phase "Spike terminé. Durée totale ci-dessus ; consigner les temps dans le doc de cadrage."
