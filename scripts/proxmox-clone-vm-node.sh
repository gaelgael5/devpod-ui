#!/usr/bin/env bash
# clone-vm-node.sh — Clone un template Proxmox en nœud Docker : création (A.1–A.9b),
# puis délègue la configuration (A.10–A.12) à configure-node.sh, qui ne dépend que
# du triplet (adresse, user, clé) et se rejoue seul sur une machine existante.
# À exécuter en root sur le host PVE, pas dans une VM.
#
# Usage :
#   bash clone-vm-node.sh <NEW_VMID> <NODE_NAME> [--ip IP/CIDR --gw GATEWAY] [OPTIONS]
#
#   IP fixe :
#     bash clone-vm-node.sh 104 pve2-docker --ip 192.168.1.50/24 --gw 192.168.1.1
#   DHCP (IP détectée via le guest agent QEMU, repli ping-sweep + ip neigh) :
#     bash clone-vm-node.sh 104 pve2-docker
#
# Arguments obligatoires (positionnels, dans cet ordre) :
#   <NEW_VMID>        VMID de la nouvelle VM (entier libre, ni VM ni LXC existant)
#   <NODE_NAME>       Nom DNS-safe de la VM  (ex. portail-dev, pve2-docker)
#
# Options réseau (omettre les deux = DHCP) :
#   --ip IP/CIDR      Adresse IP fixe avec masque  (ex. 192.168.1.50/24)
#   --gw GATEWAY      Passerelle par défaut         (ex. 192.168.1.1)
#
# Autres options :
#   --template VMID   VMID du template source      (défaut : auto-détecté)
#   --storage NOM     Stockage Proxmox cible        (défaut : même stockage que le template)
#   --dns ADDR        Serveur DNS                  (défaut : 1.1.1.1)
#   --memory N        RAM en Mo                    (défaut : 8192)
#   --cores N         Nombre de vCPU               (défaut : 4)
#   --disk SZ         Espace disque supplémentaire  (défaut : +40G)
#   --sshkey FICHIER      Clé publique SSH principale (défaut : auto-détectée dans ~/.ssh/)
#   --extra-sshkey FICH   Clé publique supplémentaire à injecter (ex. clé Windows)
#   --ciuser USER         Utilisateur cloud-init      (défaut : debian)
#   --cpu MODELE          Modèle CPU QEMU             (défaut : x86-64-v3 ; ou host)
#   --swap PCT            Swapfile en % de la RAM     (défaut : 25 ; 0 = désactivé)
#   --cleanup-on-error    Détruit la VM créée si le script échoue en cours de route
#
# Options d'intégration portail (toutes trois requises pour l'enrôlement A.9b/A.12) :
#   --portal-url URL      URL externe du portail
#   --portal-token TOKEN  Jeton d'API admin — préférer la variable d'environnement
#                         PORTAL_TOKEN, qui ne s'affiche pas dans `ps auxww`
#   --portal-pve-node NOM Nom du nœud Proxmox tel qu'enregistré dans le portail

set -euo pipefail
IFS=$'\n\t'

# ─── Valeurs par défaut ────────────────────────────────────────────────────────
TEMPLATE_VMID=""
NODE_NAME=""
IP_CIDR=""
GATEWAY=""
STORAGE=""
DNS="1.1.1.1"
MEMORY=8192
CORES=4
DISK_EXTRA="+40G"
SSH_KEY_FILE=""
EXTRA_SSH_KEY_FILE=""
CI_USER="debian"
# Les binaires compilés avec Bun (ex. claude) exigent AVX ; kvm64 (défaut Proxmox) masque AVX.
# x86-64-v3 expose AVX/AVX2/FMA, est supporté par les deux nœuds du cluster (Haswell + Raptor Lake),
# et reste live-migratable entre eux — contrairement à --cpu host qui épingle au modèle exact.
CPU_TYPE="x86-64-v3"
# Liste fermée, alignée sur celle du descripteur UI (proxmox-clone-vm-node.json).
# Un modèle inconnu ne serait rejeté que par `qm set`, APRÈS le clone : la VM
# resterait créée mais à moitié configurée. On le refuse donc avant d'y toucher.
#
# `host` expose les extensions de virtualisation (vmx/svm), donc /dev/kvm, donc
# la virtualisation imbriquée. En contrepartie il épingle la VM au CPU exact de
# son hôte : plus de migration à chaud vers un hôte différent. C'est pour ça
# qu'il reste opt-in et n'est pas le défaut.
#
# kvm64 est volontairement absent : il masque AVX, dont dépendent les binaires
# compilés avec Bun (dont `claude`).
CPU_TYPES_AUTORISES=("x86-64-v3" "host")
PORTAL_URL=""
# Accepté en variable d'environnement : un argv est lisible par tout processus
# local (`ps auxww`). L'option --portal-token reste un repli de compatibilité.
PORTAL_TOKEN="${PORTAL_TOKEN:-}"
PORTAL_PVE_NODE=""
CLEANUP_ON_ERROR=false
# Swapfile d'urgence (enabler 74ad4fdf) : sans swap, un pic mémoire transitoire
# déclenche l'OOM killer immédiatement (incident du 23/07 : networkd tué, host
# injoignable). 25 % de la RAM, borné, swappiness bas = airbag, pas matelas.
SWAP_PERCENT=25
SWAP_MIN_MB=512
SWAP_MAX_MB=8192
SWAPPINESS=10

# ─── Arguments positionnels obligatoires ─────────────────────────────────────
if [[ $# -lt 2 ]]; then
    echo "ERREUR : arguments manquants." >&2
    echo "Usage : bash $0 <NEW_VMID> <NODE_NAME> [OPTIONS]" >&2
    exit 1
fi
NEW_VMID="$1"
NODE_NAME="$2"
shift 2

# ─── Rattrapage sur échec ─────────────────────────────────────────────────────
# Entre A.2 et la fin, n'importe quel échec sous `set -e` laisserait une VM
# orpheline (VMID consommé, run suivant en échec sur A.1) et le portail sans
# rien d'exploitable à parser. Le trap EXIT garantit : fichiers temporaires
# nettoyés, commande de nettoyage affichée (ou jouée si --cleanup-on-error),
# et une DERNIÈRE ligne JSON status:error que le portail sait lire.
STAGE="préliminaires"
VM_CREEE=false
COMBINED_KEYS_FILE=""
PORTAL_RESP_FILE=""
CONFIGURE_TMP=""

on_exit() {
    local rc=$?
    # ${VAR:+...} : sous `set -u`, ne référencer que les fichiers réellement créés
    rm -f ${COMBINED_KEYS_FILE:+"$COMBINED_KEYS_FILE"} \
          ${PORTAL_RESP_FILE:+"$PORTAL_RESP_FILE"} \
          ${CONFIGURE_TMP:+"$CONFIGURE_TMP"}
    [[ $rc -eq 0 ]] && return 0
    if [[ "$VM_CREEE" == "true" ]]; then
        if [[ "$CLEANUP_ON_ERROR" == "true" ]]; then
            echo "==> --cleanup-on-error : destruction de la VM $NEW_VMID..." >&2
            qm stop "$NEW_VMID" >/dev/null 2>&1 || true
            qm destroy "$NEW_VMID" >/dev/null 2>&1 || true
            echo "    VM $NEW_VMID détruite." >&2
        else
            echo "  La VM $NEW_VMID reste créée. Nettoyage manuel :" >&2
            echo "    qm stop $NEW_VMID && qm destroy $NEW_VMID" >&2
        fi
    fi
    # Dernière ligne stdout = contrat avec le portail (parse_last_json) ; le
    # détail humain est déjà parti sur stderr au fil de l eau.
    printf '{"status":"error","stage":"%s","vmid":"%s","message":"échec à l étape %s — détail sur stderr"}\n' \
        "$STAGE" "$NEW_VMID" "$STAGE"
}
trap on_exit EXIT

# ─── Options facultatives ─────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --ip)       IP_CIDR="$2";       shift 2 ;;
        --gw)       GATEWAY="$2";       shift 2 ;;
        --template) TEMPLATE_VMID="$2"; shift 2 ;;
        --storage)  STORAGE="$2";       shift 2 ;;
        --dns)      DNS="$2";           shift 2 ;;
        --memory)   MEMORY="$2";        shift 2 ;;
        --cores)    CORES="$2";         shift 2 ;;
        --disk)     DISK_EXTRA="$2";    shift 2 ;;
        --sshkey)        SSH_KEY_FILE="$2";       shift 2 ;;
        --extra-sshkey)  EXTRA_SSH_KEY_FILE="$2"; shift 2 ;;
        --ciuser)        CI_USER="$2";            shift 2 ;;
        --cpu)           CPU_TYPE="$2";           shift 2 ;;
        --portal-url)      PORTAL_URL="$2";      shift 2 ;;
        --portal-token)    PORTAL_TOKEN="$2";    shift 2 ;;
        --portal-pve-node) PORTAL_PVE_NODE="$2"; shift 2 ;;
        --swap)            SWAP_PERCENT="$2";    shift 2 ;;
        --cleanup-on-error) CLEANUP_ON_ERROR=true; shift ;;
        *)
            echo "ERREUR : option inconnue : $1" >&2
            echo "Usage : bash $0 <NEW_VMID> <NODE_NAME> [OPTIONS]" >&2
            echo "Options : --ip --gw --template --storage --dns --memory --cores --disk --cpu --sshkey --extra-sshkey --ciuser --swap --cleanup-on-error --portal-url --portal-token --portal-pve-node" >&2
            exit 1
            ;;
    esac
done

# ─── Prérequis système ────────────────────────────────────────────────────────
echo "==> Vérification des prérequis..."

# curl et python3 : consommés en A.9b et A.10+ ; le contrôle est gratuit ici,
# leur absence à mi-parcours laisserait une VM à moitié configurée.
for cmd in qm pct pvesm ssh curl python3; do
    command -v "$cmd" &>/dev/null || {
        echo "ERREUR : '$cmd' introuvable — exécuter en root sur un host Proxmox VE." >&2
        exit 1
    }
done

# ─── Validation des arguments obligatoires ────────────────────────────────────
# --ip et --gw doivent être fournis ensemble ou pas du tout
if [[ -n "$IP_CIDR" ]] && [[ -z "$GATEWAY" ]]; then
    echo "ERREUR : --ip fourni sans --gw (ex. --gw 192.168.1.1)." >&2; exit 1
fi
if [[ -z "$IP_CIDR" ]] && [[ -n "$GATEWAY" ]]; then
    echo "ERREUR : --gw fourni sans --ip (ex. --ip 192.168.1.50/24)." >&2; exit 1
fi

USE_DHCP=false
[[ -z "$IP_CIDR" ]] && USE_DHCP=true

# Valider le stockage si précisé (auto = même stockage que le template, pas de validation)
if [[ -n "$STORAGE" && "$STORAGE" != "auto" ]]; then
    pvesm status 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$STORAGE" || {
        echo "ERREUR : stockage '$STORAGE' introuvable." >&2
        echo "  Stockages disponibles : $(pvesm status 2>/dev/null | awk 'NR>1 {print $1}' | tr '\n' ' ')" >&2
        exit 1
    }
fi

[[ "$NEW_VMID" =~ ^[0-9]+$ ]] || {
    echo "ERREUR : NEW_VMID invalide : '$NEW_VMID' — doit être un entier positif." >&2
    exit 1
}

[[ "$NODE_NAME" =~ ^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$ ]] || {
    echo "ERREUR : --name '$NODE_NAME' invalide." >&2
    echo "  Regex attendue : ^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$  (ex. pve2-docker)" >&2
    exit 1
}

# Ajouter le préfixe '+' au montant disque si absent (ex. 40G -> +40G)
[[ "$DISK_EXTRA" == +* ]] || DISK_EXTRA="+${DISK_EXTRA}"

# Swap : % entier de 0 à 100 ; taille dérivée de la RAM effective, bornée
[[ "$SWAP_PERCENT" =~ ^[0-9]+$ ]] && [[ "$SWAP_PERCENT" -le 100 ]] || {
    echo "ERREUR : --swap '$SWAP_PERCENT' invalide — entier 0..100 (%% de la RAM)." >&2
    exit 1
}
SWAP_MB=$(( MEMORY * SWAP_PERCENT / 100 ))
if [[ "$SWAP_PERCENT" -gt 0 ]]; then
    [[ "$SWAP_MB" -lt "$SWAP_MIN_MB" ]] && SWAP_MB="$SWAP_MIN_MB"
    [[ "$SWAP_MB" -gt "$SWAP_MAX_MB" ]] && SWAP_MB="$SWAP_MAX_MB"
fi

# Modèle CPU : liste fermée, validée AVANT le clone (cf. CPU_TYPES_AUTORISES)
cpu_ok=""
for modele in "${CPU_TYPES_AUTORISES[@]}"; do
    [[ "$CPU_TYPE" == "$modele" ]] && { cpu_ok=1; break; }
done
[[ -n "$cpu_ok" ]] || {
    # IFS vaut $'\n\t' dans ce script : `${tableau[*]}` collerait les valeurs
    # avec un saut de ligne. On assemble donc la liste explicitement.
    liste_cpu="$(IFS='|'; echo "${CPU_TYPES_AUTORISES[*]}")"
    echo "ERREUR : --cpu '$CPU_TYPE' invalide." >&2
    echo "  Valeurs acceptées : ${liste_cpu//|/, }" >&2
    echo "  Aucune VM n'a été créée." >&2
    exit 1
}

# `host` sans nesting côté hôte donne une VM sans /dev/kvm : le modèle CPU est
# bien passé, mais l'hyperviseur ne relaie pas les extensions. Le diagnostic
# depuis l'invité est alors trompeur — on le signale ici, à la source.
if [[ "$CPU_TYPE" == "host" ]]; then
    # `|| true` obligatoire : sous `set -e`, un `cat` sur des fichiers absents
    # (module KVM non charge) ferait echouer l'assignation, donc tout le script
    # — avant meme le clone. Une sonde de diagnostic ne doit rien interrompre.
    nested="$(cat /sys/module/kvm_intel/parameters/nested \
                  /sys/module/kvm_amd/parameters/nested 2>/dev/null | head -n1 || true)"
    if [[ "$nested" != "Y" && "$nested" != "1" ]]; then
        echo "AVERTISSEMENT : nesting inactif sur cet hôte — la VM n'aura pas /dev/kvm." >&2
        echo "  Activer :  echo 'options kvm-intel nested=1' > /etc/modprobe.d/kvm-intel.conf" >&2
        echo "             modprobe -r kvm_intel && modprobe kvm_intel   (ou reboot de l'hôte)" >&2
        echo "  Adapter kvm-intel -> kvm-amd sur un hôte AMD. La VM doit ensuite être" >&2
        echo "  ARRÊTÉE puis redémarrée : un reboot invité ne rejoue pas la définition QEMU." >&2
    fi
fi

# Valeur 'auto' passée par l'interface → traité comme vide (détection automatique)
[[ "$STORAGE" == "auto" ]] && STORAGE=""
[[ "$TEMPLATE_VMID" == "auto" ]] && TEMPLATE_VMID=""

# ─── A.1 — Vérifier que le VMID est libre (cluster-wide) ──────────────────────
STAGE="A.1 (vérification VMID)"
echo "==> A.1 — Vérification du VMID $NEW_VMID (cluster)..."

# /etc/pve est répliqué dans tout le cluster (pmxcfs) : un VMID doit être unique sur
# l'ENSEMBLE des nœuds. qm list / pct list ne voient que le nœud local et manquent un
# VMID occupé sur un autre nœud (ou un .conf orphelin), d'où un `qm clone` qui échoue
# avec "rename ... 103.conf failed: File exists". On inspecte donc les .conf de tous
# les nœuds.
if compgen -G "/etc/pve/nodes/*/qemu-server/${NEW_VMID}.conf" >/dev/null \
   || compgen -G "/etc/pve/nodes/*/lxc/${NEW_VMID}.conf" >/dev/null; then
    occupied=$(ls /etc/pve/nodes/*/qemu-server/"${NEW_VMID}".conf \
                  /etc/pve/nodes/*/lxc/"${NEW_VMID}".conf 2>/dev/null | tr '\n' ' ')
    echo "ERREUR : VMID $NEW_VMID déjà utilisé dans le cluster (VM ou LXC)." >&2
    echo "  Config(s) existante(s) : $occupied" >&2
    echo "  Choisir un autre VMID, ou supprimer si orphelin : qm destroy $NEW_VMID" >&2
    exit 1
fi

echo "    VMID $NEW_VMID : libre (cluster — aucune VM ni LXC)"

# ─── A.1 — Auto-détection du template source ──────────────────────────────────
if [[ -z "$TEMPLATE_VMID" ]]; then
    echo "    Recherche d'un template disponible..."
    while IFS= read -r vmid; do
        if qm config "$vmid" 2>/dev/null | grep -q "^template: 1"; then
            TEMPLATE_VMID="$vmid"
            TEMPLATE_NAME=$(qm config "$vmid" 2>/dev/null | grep "^name:" | awk '{print $2}')
            echo "    Template auto-détecté : ${TEMPLATE_NAME} (VMID ${TEMPLATE_VMID})"
            break
        fi
    done < <(qm list 2>/dev/null | awk 'NR>1 {print $1}')

    [[ -n "$TEMPLATE_VMID" ]] || {
        echo "ERREUR : aucun template trouvé sur ce host." >&2
        echo "  Créer un template : bash create-vm-generic.sh <VMID>" >&2
        echo "  Ou préciser : --template VMID" >&2
        exit 1
    }
else
    qm config "$TEMPLATE_VMID" 2>/dev/null | grep -q "^template: 1" || {
        echo "ERREUR : VMID $TEMPLATE_VMID n'est pas un template Proxmox." >&2
        echo "  Vérifier : qm config $TEMPLATE_VMID | grep template" >&2
        exit 1
    }
    TEMPLATE_NAME=$(qm config "$TEMPLATE_VMID" 2>/dev/null | grep "^name:" | awk '{print $2}')
    echo "    Template : ${TEMPLATE_NAME} (VMID ${TEMPLATE_VMID})"
fi

# ─── A.3 — Résolution de la clé SSH publique ─────────────────────────────────
if [[ -z "$SSH_KEY_FILE" ]]; then
    for candidate in ~/.ssh/id_ed25519.pub ~/.ssh/id_ecdsa.pub ~/.ssh/id_rsa.pub; do
        if [[ -f "$candidate" ]]; then
            SSH_KEY_FILE="$candidate"
            echo "    Clé SSH auto-détectée : $SSH_KEY_FILE"
            break
        fi
    done
    [[ -n "$SSH_KEY_FILE" ]] || {
        echo "ERREUR : aucune clé publique SSH trouvée dans ~/.ssh/." >&2
        echo "  Générer une clé : ssh-keygen -t ed25519" >&2
        echo "  Ou préciser : --sshkey /chemin/vers/cle.pub" >&2
        exit 1
    }
else
    [[ -f "$SSH_KEY_FILE" ]] || {
        echo "ERREUR : fichier clé SSH introuvable : $SSH_KEY_FILE" >&2
        exit 1
    }
fi

# Dériver le chemin de la clé privée (même chemin sans .pub) pour SSH post-boot
SSH_PRIVATE_KEY="${SSH_KEY_FILE%.pub}"
[[ -f "$SSH_PRIVATE_KEY" ]] || {
    echo "ERREUR : clé privée introuvable : $SSH_PRIVATE_KEY" >&2
    echo "  (déduite de --sshkey ${SSH_KEY_FILE})" >&2
    exit 1
}

# Valider --extra-sshkey si fourni
if [[ -n "$EXTRA_SSH_KEY_FILE" ]]; then
    [[ -f "$EXTRA_SSH_KEY_FILE" ]] || {
        echo "ERREUR : --extra-sshkey : fichier introuvable : $EXTRA_SSH_KEY_FILE" >&2
        exit 1
    }
fi

# Extraire l'adresse IP seule (sans le masque) — vide si DHCP, remplie plus bas
IP_ADDR=""
[[ -n "$IP_CIDR" ]] && IP_ADDR="${IP_CIDR%%/*}"

# ─── Résumé des paramètres ────────────────────────────────────────────────────
echo ""
echo "==> Paramètres retenus :"
echo "    Nouveau VMID   : $NEW_VMID"
echo "    Nom du nœud    : $NODE_NAME"
echo "    Template source: ${TEMPLATE_NAME} (VMID ${TEMPLATE_VMID})"
if [[ "$USE_DHCP" == "true" ]]; then
echo "    Réseau         : DHCP (IP détectée après démarrage)"
else
echo "    IP / Passerelle: $IP_CIDR via $GATEWAY"
fi
if [[ -n "$STORAGE" ]]; then
echo "    Stockage       : $STORAGE"
else
echo "    Stockage       : même que le template (défaut)"
fi
echo "    DNS            : $DNS"
echo "    vCPU / RAM     : ${CORES} cores / ${MEMORY} Mo"
echo "    Modèle CPU     : $CPU_TYPE"
echo "    Disque ajouté  : $DISK_EXTRA"
if [[ "$SWAP_PERCENT" -gt 0 ]]; then
echo "    Swapfile       : ${SWAP_MB} Mo (${SWAP_PERCENT}% RAM, swappiness ${SWAPPINESS})"
else
echo "    Swapfile       : désactivé (--swap 0)"
fi
echo "    Clé SSH        : $SSH_KEY_FILE"
[[ -n "$EXTRA_SSH_KEY_FILE" ]] && \
echo "    Clé SSH extra  : $EXTRA_SSH_KEY_FILE"
echo "    Utilisateur CI : $CI_USER"
echo ""

# ─── A.2 — Cloner le template ─────────────────────────────────────────────────
STAGE="A.2 (clonage)"
echo "==> A.2 — Clonage du template VMID ${TEMPLATE_VMID} -> VMID ${NEW_VMID}..."
echo "    (clone complet --full, peut prendre 1 à 5 minutes)"

CLONE_ARGS=("$TEMPLATE_VMID" "$NEW_VMID" --name "$NODE_NAME" --full)
[[ -n "$STORAGE" ]] && CLONE_ARGS+=(--storage "$STORAGE")
qm clone "${CLONE_ARGS[@]}"
VM_CREEE=true

echo "    Clone terminé."

# ─── A.3 — Injecter la clé SSH et définir un mot de passe console ────────────
echo ""
STAGE="A.3 (clé SSH + mot de passe console)"
echo "==> A.3 — Injection de la clé SSH publique + mot de passe console..."

# Mot de passe aléatoire pour accès console Proxmox (noVNC / qm terminal)
CI_PASSWORD=$(openssl rand -base64 12)

# Construire le fichier de clés à injecter (principale + extra si fournie)
COMBINED_KEYS_FILE=$(mktemp /tmp/sshkeys-XXXXXX.pub)
cat "$SSH_KEY_FILE" > "$COMBINED_KEYS_FILE"
if [[ -n "$EXTRA_SSH_KEY_FILE" ]]; then
    echo "" >> "$COMBINED_KEYS_FILE"
    cat "$EXTRA_SSH_KEY_FILE" >> "$COMBINED_KEYS_FILE"
fi
# Normaliser les fins de ligne (fichiers .pub copiés depuis Windows ont des CRLF
# qui corrompent authorized_keys et font rejeter toutes les clés par Proxmox).
sed -i 's/\r//' "$COMBINED_KEYS_FILE"

qm set "$NEW_VMID" --sshkeys "$COMBINED_KEYS_FILE" --ciuser "$CI_USER" --cipassword "$CI_PASSWORD"

echo "    Clé(s) injectée(s) pour l'utilisateur '$CI_USER'."
# Le mot de passe console ne s'affiche qu'en interactif : sur un run déclenché
# par le portail, stdout part dans les logs de la tâche et un secret n'a rien à
# y faire. Un admin peut toujours le reposer : qm set <vmid> --cipassword.
if [[ -t 1 ]]; then
    echo ""
    echo "  ┌─────────────────────────────────────────────────┐"
    echo "  │  Accès console (Proxmox noVNC / qm terminal)   │"
    echo "  │  Login    : $CI_USER                            │"
    echo "  │  Password : $CI_PASSWORD                        │"
    echo "  └─────────────────────────────────────────────────┘"
    echo ""
else
    echo "    Mot de passe console non affiché (sortie non interactive)."
fi

# ─── A.4 — Configurer la mémoire, le CPU et le modèle CPU ────────────────────
echo ""
STAGE="A.4 (ressources)"
echo "==> A.4 — Configuration des ressources (${CORES} vCPU / ${MEMORY} Mo RAM / CPU ${CPU_TYPE})..."

# --cpu appliqué explicitement même sur un clone : un template créé avec l'ancien
# script (sans --cpu) hérite de kvm64 qui masque AVX. qm set corrige ça défensivement.
# --onboot 1 : la VM (nœud Docker) doit redémarrer automatiquement au boot du host
# PVE, sinon un reboot du host laisse le nœud éteint et indisponible pour le portail.
qm set "$NEW_VMID" --memory "$MEMORY" --cores "$CORES" --cpu "$CPU_TYPE" --onboot 1

echo "    Ressources configurées (démarrage automatique au boot du host activé)."

# ─── A.5 — Agrandir le disque avant le premier démarrage ─────────────────────
echo ""
STAGE="A.5 (disque)"
echo "==> A.5 — Agrandissement du disque ($DISK_EXTRA) avant le premier démarrage..."

# Détecter le nom du disque principal (scsi0, virtio0…) en excluant cloud-init et cd-rom
DISK_DEV=$(qm config "$NEW_VMID" 2>/dev/null \
    | grep -E '^(scsi|virtio|sata)[0-9]+:' \
    | grep -v 'media=cdrom' \
    | grep -v 'cloudinit' \
    | head -1 \
    | cut -d: -f1)

[[ -n "$DISK_DEV" ]] || {
    echo "ERREUR : aucun disque principal détecté dans la config de la VM." >&2
    echo "  Vérifier : qm config $NEW_VMID" >&2
    exit 1
}
echo "    Disque détecté : $DISK_DEV"

qm resize "$NEW_VMID" "$DISK_DEV" "$DISK_EXTRA"

echo "    Disque agrandi de $DISK_EXTRA."

# ─── A.6 — Configurer le réseau via cloud-init ───────────────────────────────
echo ""
STAGE="A.6 (réseau cloud-init)"
if [[ "$USE_DHCP" == "true" ]]; then
    echo "==> A.6 — Configuration réseau via cloud-init (DHCP)..."
    qm set "$NEW_VMID" --ipconfig0 "ip=dhcp"
    echo "    DHCP configuré (DNS fourni par le serveur DHCP)."
else
    echo "==> A.6 — Configuration de l'IP fixe via cloud-init ($IP_CIDR gw $GATEWAY)..."
    qm set "$NEW_VMID" \
        --ipconfig0  "ip=${IP_CIDR},gw=${GATEWAY}" \
        --nameserver "$DNS"
    echo "    IP configurée."
fi

# Guest agent QEMU : permet de lire l'IP assignée DEPUIS l'intérieur du guest
# (détection fiable, indépendante du subnet/bridge du host). Doit être activé
# AVANT le démarrage. Sans qemu-guest-agent dans le template, `qm guest cmd`
# échoue simplement → on retombe sur le ping-sweep + arp (A.8).
qm set "$NEW_VMID" --agent enabled=1

# ─── A.7 — Démarrer la VM ────────────────────────────────────────────────────
echo ""
STAGE="A.7 (démarrage)"
echo "==> A.7 — Démarrage de la VM VMID $NEW_VMID..."

qm start "$NEW_VMID"

echo "    VM démarrée. Attente de cloud-init et SSH..."

# ─── A.8 — Récupérer l'IP DHCP ───────────────────────────────────────────────
# Primaire : guest agent QEMU (lit l'IP depuis le guest, fiable quel que soit le
# subnet/bridge). Repli : ping sweep du /24 du bridge + lecture de la table de
# voisinage du kernel via `ip neigh` (iproute2, toujours présent) — PAS `arp`,
# qui vient de net-tools, absent par défaut sur Debian 12/PVE 8 : son échec
# silencieux (2>/dev/null) était indiscernable d'une table vide.
_ip_from_agent() {
    # Première IPv4 non-loopback rapportée par l'agent (JSON network-get-interfaces).
    qm guest cmd "$NEW_VMID" network-get-interfaces 2>/dev/null \
        | grep -oP '"ip-address"\s*:\s*"\K[0-9.]+' \
        | grep -vE '^127\.' \
        | head -1
}
if [[ "$USE_DHCP" == "true" ]]; then
    echo ""
    STAGE="A.8 (détection IP DHCP)"
    echo "==> A.8 — Détection de l'IP DHCP (guest agent puis ping-sweep, max 120s)..."

    BRIDGE=$(qm config "$NEW_VMID" 2>/dev/null | grep '^net0:' \
        | grep -oP 'bridge=[^,]+' | cut -d= -f2)
    MAC=$(qm config "$NEW_VMID" 2>/dev/null | grep '^net0:' \
        | grep -oP 'virtio=[0-9A-Fa-f:]+' | cut -d= -f2 | tr '[:upper:]' '[:lower:]')

    [[ -n "$MAC" ]] || { echo "ERREUR : MAC de net0 introuvable." >&2; exit 1; }
    BRIDGE_IFACE="${BRIDGE:-vmbr0}"
    echo "    MAC : $MAC  Bridge : $BRIDGE_IFACE"

    BRIDGE_NET=$(ip -4 addr show dev "$BRIDGE_IFACE" 2>/dev/null \
        | grep -oP 'inet \K\d+\.\d+\.\d+' | head -1)
    [[ -n "$BRIDGE_NET" ]] \
        && echo "    Subnet : ${BRIDGE_NET}.0/24 — ping sweep à ~30s" \
        || echo "    AVERTISSEMENT : subnet du bridge introuvable — sweep désactivé"

    LAST_SWEEP=-30
    ELAPSED=0
    while [[ $ELAPSED -lt 120 ]]; do
        # 1) Guest agent (fiable, indépendant du subnet/bridge)
        IP_ADDR=$(_ip_from_agent) || true
        [[ -n "$IP_ADDR" ]] && { echo ""; echo "    (détectée via guest agent)"; break; }

        # 2) Repli : table de voisinage du kernel (peuplée par le ping-sweep ci-dessous)
        IP_ADDR=$(ip -4 neigh show 2>/dev/null | awk -v mac="$MAC" 'tolower($5)==mac {print $1; exit}') || true
        [[ -n "$IP_ADDR" ]] && break

        # Ping sweep toutes les 30s dès 30s : force la VM à répondre par ARP
        if [[ -n "$BRIDGE_NET" && $ELAPSED -ge 30 && $(( ELAPSED - LAST_SWEEP )) -ge 30 ]]; then
            printf "\r    %3ds — ping sweep %s.0/24...%-40s" "$ELAPSED" "$BRIDGE_NET" ""
            PING_PIDS=()
            for i in $(seq 1 254); do
                ping -c1 -W1 -q "${BRIDGE_NET}.${i}" &>/dev/null &
                PING_PIDS+=($!)
            done
            wait "${PING_PIDS[@]}" 2>/dev/null || true
            LAST_SWEEP=$ELAPSED
            IP_ADDR=$(ip -4 neigh show 2>/dev/null | awk -v mac="$MAC" 'tolower($5)==mac {print $1; exit}') || true
            if [[ -n "$IP_ADDR" ]]; then echo ""; break; fi
        fi

        VM_STATUS=$(qm status "$NEW_VMID" 2>/dev/null | awk '{print $2}' || echo "?")
        printf "\r    %3ds — attente DHCP ($VM_STATUS)%-50s" "$ELAPSED" ""
        sleep 5
        ELAPSED=$(( ELAPSED + 5 ))
    done
    echo ""

    if [[ -z "$IP_ADDR" ]]; then
        echo ""
        echo "  IP DHCP non détectée après 120s (ni guest agent, ni table de voisinage)."
        echo "  La VM est démarrée ($(qm status "$NEW_VMID" 2>/dev/null))."
        echo "  Causes probables : qemu-guest-agent absent du template, ou pas de"
        echo "  bail DHCP sur le bridge de la VM."
        echo "  Récupérer l'IP via : qm terminal $NEW_VMID  -> ip addr"
        echo ""
        if [[ -t 0 ]]; then
            printf "  Entrer l'IP manuellement : "
            read -r IP_ADDR
            IP_ADDR="${IP_ADDR// /}"
        fi
        [[ -n "$IP_ADDR" ]] || {
            echo "ERREUR : IP non fournie. VM reste démarrée (VMID $NEW_VMID)." >&2
            exit 1
        }
    fi
    echo "    IP DHCP détectée : $IP_ADDR"
fi

# ─── A.9 — Attendre que SSH soit disponible ───────────────────────────────────
# On attend que cloud-init ait écrit authorized_keys (module ssh, stage 'config').
# sshd ouvre le port 22 AVANT cela : tester le port ne prouve rien, on teste le
# vrai SSH par clé jusqu'à succès.
#
# Timeout : observé ~20s au 1er boot ; pire cas cloud-init sur host/ZFS chargé
# ~90s. Plafond à 120s. Au-delà ce n'est plus de la lenteur mais une panne
# (clé non injectée, réseau cassé) : on échoue et on diagnostique avec LAST_ERR.
echo ""
STAGE="A.9 (attente SSH)"
echo "==> A.9 — Attente de SSH sur $IP_ADDR (max 120s)..."
echo "    (sshd ouvre le port avant que cloud-init n'écrive authorized_keys)"

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

# Une seule boucle : retenter le vrai SSH jusqu'à succès. On capture stderr
# (LAST_ERR) pour afficher la vraie cause en cas d'échec, jamais 2>/dev/null aveugle.
#
# -n est CRITIQUE : le script est lancé via `curl | bash`, donc stdin de bash est
# le pipe curl. Sans -n, ssh hérite de ce pipe et CONSOMME le reste du script
# (boucle, A.11, résumé) → bash n'a plus rien à lire et s'arrête silencieusement
# juste après cet en-tête. -n redirige stdin de ssh depuis /dev/null.
ELAPSED=0
LAST_ERR=""
until LAST_ERR=$(ssh -n "${SSH_OPTS[@]}" "${CI_USER}@${IP_ADDR}" "exit 0" 2>&1); do
    if [[ $ELAPSED -ge 120 ]]; then
        echo "" >&2
        echo "ERREUR : SSH indisponible sur ${CI_USER}@${IP_ADDR} après 120s." >&2
        echo "  Dernière erreur SSH : ${LAST_ERR:-<aucune sortie>}" >&2
        echo "  État VM    : $(qm status "$NEW_VMID" 2>/dev/null)" >&2
        echo "  Diagnostic : ssh -v -i $SSH_PRIVATE_KEY ${CI_USER}@${IP_ADDR}" >&2
        exit 1
    fi
    printf "\r    %3ds — en attente de SSH..." "$ELAPSED"
    sleep 5
    ELAPSED=$(( ELAPSED + 5 ))
done
echo ""
echo "    SSH opérationnel sur ${IP_ADDR}."

# ─── Rafraîchir known_hosts du host PVE ──────────────────────────────────────
# La VM vient d'être (re)créée à cette IP : toute entrée known_hosts existante est
# périmée et provoque "REMOTE HOST IDENTIFICATION HAS CHANGED" sur les ssh manuels.
# On purge l'ancienne empreinte et on pré-enregistre la nouvelle (évite aussi le
# prompt yes/no au premier ssh debian@IP depuis le host).
if [[ -d ~/.ssh ]]; then
    ssh-keygen -R "$IP_ADDR" 2>/dev/null || true
    ssh-keyscan -T 5 "$IP_ADDR" >> ~/.ssh/known_hosts 2>/dev/null || true
    echo "    known_hosts du host PVE rafraîchi pour $IP_ADDR."
fi

# ─── A.9b — Clé SSH portail (si portail configuré et host de type ssh) ──────
# Génère la paire ed25519 côté portail, enregistre l'adresse dans config.yaml,
# et injecte la clé publique du portail dans authorized_keys de la VM.
# Non-fatal si le host n'existe pas encore dans le portail (404/422 → avertissement).
PORTAL_KEY_PATH=""
if [[ -n "$PORTAL_URL" && -n "$PORTAL_TOKEN" ]]; then
    echo ""
    STAGE="A.9b (clé SSH portail)"
    echo "==> A.9b — Génération de la clé SSH portail pour '$NODE_NAME'..."

    PORTAL_RESP_FILE=$(mktemp /tmp/portal-keygen-XXXXXX.json)

    # Le jeton passe par un fichier de config curl lu sur stdin (-K -), jamais
    # en argv : l argv de curl est lisible par tout processus local (ps auxww).
    HTTP_CODE=$(curl -sS \
        -w "%{http_code}" \
        -o "$PORTAL_RESP_FILE" \
        -X POST \
        "${PORTAL_URL}/admin/hosts/${NODE_NAME}/generate-ssh-key?address=${CI_USER}@${IP_ADDR}&proxmox_node=${PORTAL_PVE_NODE}" \
        -K - 2>/dev/null <<CURL_CFG
header = "Authorization: Bearer ${PORTAL_TOKEN}"
CURL_CFG
    ) || HTTP_CODE="000"

    if [[ "$HTTP_CODE" == "200" ]]; then
        PORTAL_PUBKEY=$(python3 -c \
            "import sys, json; print(json.load(open('${PORTAL_RESP_FILE}')).get('public_key',''))" \
            2>/dev/null || true)
        if [[ -n "$PORTAL_PUBKEY" ]]; then
            # Injecter la pubkey du portail dans authorized_keys (sans doublon)
            ssh -n "${SSH_OPTS[@]}" "${CI_USER}@${IP_ADDR}" bash <<REMOTE
set -e
mkdir -p ~/.ssh
chmod 700 ~/.ssh
grep -qxF "${PORTAL_PUBKEY}" ~/.ssh/authorized_keys 2>/dev/null \
    || echo "${PORTAL_PUBKEY}" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
REMOTE
            PORTAL_KEY_PATH="/data/keys/hosts/${NODE_NAME}_ed25519"
            echo "    Clé portail générée et injectée dans authorized_keys."
            echo "    Le portail peut désormais accéder à ${CI_USER}@${IP_ADDR}."
        else
            echo "AVERTISSEMENT : réponse portail invalide (public_key absent) — A.9b ignorée." >&2
        fi
    elif [[ "$HTTP_CODE" == "404" ]]; then
        echo "AVERTISSEMENT : host '${NODE_NAME}' introuvable dans le portail (404) — A.9b ignorée." >&2
        echo "  Créer le host dans l'admin du portail avant de relancer." >&2
    elif [[ "$HTTP_CODE" == "422" ]]; then
        echo "AVERTISSEMENT : host '${NODE_NAME}' n'est pas de type 'ssh' (422) — A.9b ignorée." >&2
    elif [[ "$HTTP_CODE" == "000" ]]; then
        echo "AVERTISSEMENT : portail inaccessible — A.9b ignorée." >&2
    else
        echo "AVERTISSEMENT : erreur portail HTTP ${HTTP_CODE} — A.9b ignorée." >&2
    fi
    rm -f "$PORTAL_RESP_FILE"
fi

# ─── A.10 → A.12 — Configuration du nœud (déléguée à configure-node.sh) ─────
# La création s'arrête ici : la machine répond en SSH. Tout ce qui suit ne
# dépend que du triplet (adresse, user, clé) et vit dans configure-node.sh,
# rejouable seul sur une machine existante (enabler 7c739d1f). Ce script
# n'écrit pas le JSON final : le descripteur est composé ci-dessous.
CONFIGURE_URL="https://raw.githubusercontent.com/gaelgael5/devpod-ui/refs/heads/dev/scripts/configure-node.sh"
# Exécution locale si le script est à côté (dépôt cloné) ; sinon téléchargé —
# le cas `curl | bash`, où BASH_SOURCE est vide.
CONFIGURE_SH="$(dirname "${BASH_SOURCE[0]:-.}")/configure-node.sh"
if [[ ! -f "$CONFIGURE_SH" ]]; then
    CONFIGURE_TMP=$(mktemp /tmp/configure-node-XXXXXX.sh)
    curl -fsSL "$CONFIGURE_URL" -o "$CONFIGURE_TMP" || {
        echo "ERREUR : configure-node.sh introuvable (ni à côté du script, ni $CONFIGURE_URL)." >&2
        echo "  La VM est créée et joignable : ssh ${CI_USER}@${IP_ADDR} -i $SSH_PRIVATE_KEY" >&2
        exit 1
    }
    CONFIGURE_SH="$CONFIGURE_TMP"
fi

CONFIGURE_ARGS=(
    --address "$IP_ADDR"
    --user "$CI_USER"
    --key "$SSH_PRIVATE_KEY"
    --node-name "$NODE_NAME"
    --swap "$SWAP_PERCENT"
    --cpu-type "$CPU_TYPE"
)
# L'enrôlement ne se transmet que complet (URL + jeton) : un jeton seul en
# environnement ne doit pas déclencher la validation portail de configure-node.
ENROLL_TOKEN=""
if [[ -n "$PORTAL_URL" && -n "$PORTAL_TOKEN" ]]; then
    CONFIGURE_ARGS+=(--portal-url "$PORTAL_URL")
    ENROLL_TOKEN="$PORTAL_TOKEN"
fi
STAGE="A.10+ (configure-node)"
# stdin < /dev/null : ce script peut tourner en `curl | bash` ; sans redirection,
# un enfant qui lirait stdin consommerait le reste du script (cf. A.9).
# Le jeton passe en environnement, jamais en argv (lisible dans ps auxww).
PORTAL_TOKEN="$ENROLL_TOKEN" bash "$CONFIGURE_SH" "${CONFIGURE_ARGS[@]}" < /dev/null

# Sémantique inchangée : l'enrôlement (A.12) n'a lieu que si portail configuré,
# et un échec de configuration a déjà interrompu le script (set -e) avant ici.
ENROLLED=false
if [[ -n "$PORTAL_URL" && -n "$PORTAL_TOKEN" ]]; then
    ENROLLED=true
fi

# ─── Résumé ───────────────────────────────────────────────────────────────────
echo ""
echo "======================================================"
echo "  Nœud créé et configuré : $NODE_NAME (VMID $NEW_VMID)"
echo "======================================================"
echo ""
if [[ "$USE_DHCP" == "true" ]]; then
echo "  IP      : $IP_ADDR  (DHCP — noter cette adresse)"
else
echo "  IP      : $IP_ADDR  (fixe)"
fi
echo "  SSH     : ssh ${CI_USER}@${IP_ADDR} -i $SSH_PRIVATE_KEY"
echo ""
if [[ "$ENROLLED" == "true" ]]; then
    echo "  Enrôlement docker-tls : effectué (portail notifié)"
elif [[ -n "$PORTAL_KEY_PATH" ]]; then
    echo "  Enrôlement SSH : clé portail générée, adresse enregistrée"
    echo "  Le portail peut se connecter : ssh ${CI_USER}@${IP_ADDR}"
else
    echo "Prochaines étapes :"
    echo "  1. Étape 3 (post-install) : outils requis, NTP, pare-feu"
    echo "     ssh ${CI_USER}@${IP_ADDR}"
    echo "  2. Enrôlement dans le portail :"
    echo "     Suivre : documentations/fr/installation-first-node.md"
fi
echo ""

# ─── Résumé JSON (dernière ligne — parsée par le portail) ────────────────────
# vmid et proxmox_node sont obligatoires pour que le portail puisse déclencher
# le destroy_script lors de la suppression du host.
# ci_password : mot de passe console Proxmox (noVNC) généré en A.3. Émis
# seulement en interactif — sur un run portail, stdout part dans les logs de la
# tâche et aucun consommateur ne lit ce champ (vérifié au ticket 81cbc93a).
[[ -t 1 ]] || CI_PASSWORD=""
if [[ "$ENROLLED" == "true" ]]; then
    printf '{"status":"ok","name":"%s","address":"%s","type":"docker-tls","docker_host":"tcp://%s:2376","ssh_user":"%s","ssh_port":22,"key_path":"/data/certs/portal","vmid":"%s","proxmox_node":"%s","ci_password":"%s"}\n' \
        "$NODE_NAME" "$IP_ADDR" "$IP_ADDR" "$CI_USER" "$NEW_VMID" "$PORTAL_PVE_NODE" "$CI_PASSWORD"
elif [[ -n "$PORTAL_KEY_PATH" ]]; then
    printf '{"status":"ok","name":"%s","address":"%s","type":"ssh","ssh_user":"%s","ssh_port":22,"key_path":"%s","vmid":"%s","proxmox_node":"%s","ci_password":"%s"}\n' \
        "$NODE_NAME" "$CI_USER@$IP_ADDR" "$CI_USER" "$PORTAL_KEY_PATH" "$NEW_VMID" "$PORTAL_PVE_NODE" "$CI_PASSWORD"
else
    printf '{"status":"ok","name":"%s","address":"%s","ssh_user":"%s","ssh_port":22,"vmid":"%s","proxmox_node":"%s","ci_password":"%s"}\n' \
        "$NODE_NAME" "$IP_ADDR" "$CI_USER" "$NEW_VMID" "$PORTAL_PVE_NODE" "$CI_PASSWORD"
fi
