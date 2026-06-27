#!/usr/bin/env bash
# clone-vm-node.sh — Clone un template Proxmox et configure un nœud Docker (étapes A.1–A.11).
# À exécuter en root sur le host PVE, pas dans une VM.
#
# Usage :
#   bash clone-vm-node.sh <NEW_VMID> <NODE_NAME> [--ip IP/CIDR --gw GATEWAY] [OPTIONS]
#
#   IP fixe :
#     bash clone-vm-node.sh 104 pve2-docker --ip 192.168.1.50/24 --gw 192.168.1.1
#   DHCP (IP détectée automatiquement via tcpdump ARP) :
#     bash clone-vm-node.sh 104 pve2-docker
#
# Arguments obligatoires :
#   <NEW_VMID>        VMID de la nouvelle VM (entier libre, ni VM ni LXC existant)
#   --name NOM        Nom DNS-safe de la VM  (ex. portail-dev, pve2-docker)
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
#   --cpu MODELE          Modèle CPU QEMU             (défaut : x86-64-v3)

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
PORTAL_URL=""
PORTAL_TOKEN=""
PORTAL_PVE_NODE=""

# ─── Arguments positionnels obligatoires ─────────────────────────────────────
if [[ $# -lt 2 ]]; then
    echo "ERREUR : arguments manquants." >&2
    echo "Usage : bash $0 <NEW_VMID> <NODE_NAME> [OPTIONS]" >&2
    exit 1
fi
NEW_VMID="$1"
NODE_NAME="$2"
shift 2

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
        *)
            echo "ERREUR : option inconnue : $1" >&2
            echo "Options : --name --ip --gw --template --storage --dns --memory --cores --disk --cpu --sshkey --extra-sshkey --ciuser --portal-url --portal-token --portal-pve-node" >&2
            exit 1
            ;;
    esac
done

# ─── Prérequis système ────────────────────────────────────────────────────────
echo "==> Vérification des prérequis..."

for cmd in qm pct pvesm ssh; do
    command -v "$cmd" &>/dev/null || {
        echo "ERREUR : '$cmd' introuvable — exécuter en root sur un host Proxmox VE." >&2
        exit 1
    }
done

# ─── Validation des arguments obligatoires ────────────────────────────────────
[[ -n "$NODE_NAME" ]] || { echo "ERREUR : --name est obligatoire (ex. portail-dev)." >&2; exit 1; }

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

# Valeur 'auto' passée par l'interface → traité comme vide (détection automatique)
[[ "$STORAGE" == "auto" ]] && STORAGE=""
[[ "$TEMPLATE_VMID" == "auto" ]] && TEMPLATE_VMID=""

# ─── A.1 — Vérifier que le VMID est libre (cluster-wide) ──────────────────────
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
echo "    Clé SSH        : $SSH_KEY_FILE"
[[ -n "$EXTRA_SSH_KEY_FILE" ]] && \
echo "    Clé SSH extra  : $EXTRA_SSH_KEY_FILE"
echo "    Utilisateur CI : $CI_USER"
echo ""

# ─── A.2 — Cloner le template ─────────────────────────────────────────────────
echo "==> A.2 — Clonage du template VMID ${TEMPLATE_VMID} -> VMID ${NEW_VMID}..."
echo "    (clone complet --full, peut prendre 1 à 5 minutes)"

CLONE_ARGS=("$TEMPLATE_VMID" "$NEW_VMID" --name "$NODE_NAME" --full)
[[ -n "$STORAGE" ]] && CLONE_ARGS+=(--storage "$STORAGE")
qm clone "${CLONE_ARGS[@]}"

echo "    Clone terminé."

# ─── A.3 — Injecter la clé SSH et définir un mot de passe console ────────────
echo ""
echo "==> A.3 — Injection de la clé SSH publique + mot de passe console..."

# Mot de passe aléatoire pour accès console Proxmox (noVNC / qm terminal)
CI_PASSWORD=$(openssl rand -base64 12)

# Construire le fichier de clés à injecter (principale + extra si fournie)
COMBINED_KEYS_FILE=$(mktemp /tmp/sshkeys-XXXXXX.pub)
trap 'rm -f "$COMBINED_KEYS_FILE"' EXIT
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
echo ""
echo "  ┌─────────────────────────────────────────────────┐"
echo "  │  Accès console (Proxmox noVNC / qm terminal)   │"
echo "  │  Login    : $CI_USER                            │"
echo "  │  Password : $CI_PASSWORD                        │"
echo "  └─────────────────────────────────────────────────┘"
echo ""

# ─── A.4 — Configurer la mémoire, le CPU et le modèle CPU ────────────────────
echo ""
echo "==> A.4 — Configuration des ressources (${CORES} vCPU / ${MEMORY} Mo RAM / CPU ${CPU_TYPE})..."

# --cpu appliqué explicitement même sur un clone : un template créé avec l'ancien
# script (sans --cpu) hérite de kvm64 qui masque AVX. qm set corrige ça défensivement.
# --onboot 1 : la VM (nœud Docker) doit redémarrer automatiquement au boot du host
# PVE, sinon un reboot du host laisse le nœud éteint et indisponible pour le portail.
qm set "$NEW_VMID" --memory "$MEMORY" --cores "$CORES" --cpu "$CPU_TYPE" --onboot 1

echo "    Ressources configurées (démarrage automatique au boot du host activé)."

# ─── A.5 — Agrandir le disque avant le premier démarrage ─────────────────────
echo ""
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

# ─── A.7 — Démarrer la VM ────────────────────────────────────────────────────
echo ""
echo "==> A.7 — Démarrage de la VM VMID $NEW_VMID..."

qm start "$NEW_VMID"

echo "    VM démarrée. Attente de cloud-init et SSH..."

# ─── A.8 — Récupérer l'IP DHCP via ping sweep + arp -n ──────────────────────
# Séquence : attendre ~30s que la VM démarre et obtienne son bail DHCP, puis
# pinguer tous les hôtes du /24 en parallèle. La VM répond à l'ARP request
# du host PVE → son entrée apparaît dans la table ARP → arp -n | grep <MAC>.
if [[ "$USE_DHCP" == "true" ]]; then
    echo ""
    echo "==> A.8 — Détection de l'IP DHCP (max 120s)..."

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
        # Lire la table ARP du kernel
        IP_ADDR=$(arp -n 2>/dev/null | awk -v mac="$MAC" 'tolower($3) == mac {print $1; exit}') || true
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
            IP_ADDR=$(arp -n 2>/dev/null | awk -v mac="$MAC" 'tolower($3) == mac {print $1; exit}') || true
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
        echo "  IP DHCP non détectée après 120s."
        echo "  La VM est démarrée ($(qm status "$NEW_VMID" 2>/dev/null))."
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

# Les commandes d'élévation : sudo pour un utilisateur non-root, rien pour root
if [[ "$CI_USER" == "root" ]]; then
    SUDO=""
else
    SUDO="sudo"
fi

# ─── A.9b — Clé SSH portail (si portail configuré et host de type ssh) ──────
# Génère la paire ed25519 côté portail, enregistre l'adresse dans config.yaml,
# et injecte la clé publique du portail dans authorized_keys de la VM.
# Non-fatal si le host n'existe pas encore dans le portail (404/422 → avertissement).
PORTAL_KEY_PATH=""
if [[ -n "$PORTAL_URL" && -n "$PORTAL_TOKEN" ]]; then
    echo ""
    echo "==> A.9b — Génération de la clé SSH portail pour '$NODE_NAME'..."

    PORTAL_RESP_FILE=$(mktemp /tmp/portal-keygen-XXXXXX.json)
    # Étend le trap EXIT pour nettoyer également ce fichier temporaire
    trap 'rm -f "$COMBINED_KEYS_FILE" "$PORTAL_RESP_FILE"' EXIT

    HTTP_CODE=$(curl -sS \
        -w "%{http_code}" \
        -o "$PORTAL_RESP_FILE" \
        -X POST \
        "${PORTAL_URL}/admin/hosts/${NODE_NAME}/generate-ssh-key?address=${CI_USER}@${IP_ADDR}&proxmox_node=${PORTAL_PVE_NODE}" \
        -H "Authorization: Bearer ${PORTAL_TOKEN}" 2>/dev/null) || HTTP_CODE="000"

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

# ─── A.10 — Installer les paquets système requis ─────────────────────────────
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

# ─── A.11 — Vérifier et finaliser le hostname ────────────────────────────────
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

# ─── A.12 — Enrôlement dans le portail (optionnel) ───────────────────────────
ENROLLED=false
if [[ -n "$PORTAL_URL" && -n "$PORTAL_TOKEN" ]]; then
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
# ci_password : mot de passe console Proxmox (noVNC) généré en A.3.
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
