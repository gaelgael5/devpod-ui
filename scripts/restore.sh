#!/usr/bin/env bash
# restore.sh — Restaure /data depuis un backup chiffré age (§G-35, §G-36)
#
# §G-35 : AVERTISSEMENT — Ce restore restaure uniquement :
#   ✓ La CA et les clés de confiance (mTLS)
#   ✓ La configuration (config.yaml, .env)
#   ✓ Les clés SSH git
#   ✓ L'état DevPod local (DEVPOD_HOME)
#   ✗ Les workspaces actifs (ils vivent dans les daemons Docker des nœuds)
#   Après restore : les workspaces doivent être re-provisionnés via devpod up.
#
# Usage :
#   AGE_IDENTITY=/root/age-backup.key bash scripts/restore.sh /backup/portal-backup-xxx.tar.gz.age
#
# Variables d'environnement :
#   DATA_ROOT       Racine de destination (défaut : /data)
#   AGE_IDENTITY    Fichier clé privée age (OBLIGATOIRE)
set -euo pipefail

DATA_ROOT="${DATA_ROOT:-/data}"
ARCHIVE="${1:-}"

if [[ -z "$ARCHIVE" ]]; then
    echo "Usage : $0 <archive.tar.gz.age>" >&2
    exit 1
fi

if [[ ! -f "$ARCHIVE" ]]; then
    echo "ERREUR : archive introuvable : $ARCHIVE" >&2
    exit 1
fi

if [[ -z "${AGE_IDENTITY:-}" ]]; then
    echo "ERREUR : AGE_IDENTITY non défini (chemin vers la clé privée age)." >&2
    exit 1
fi

for cmd in age tar; do
    command -v "$cmd" &>/dev/null || { echo "ERREUR : $cmd introuvable" >&2; exit 1; }
done

# ── Avertissement OBLIGATOIRE (§G-35) ────────────────────────────────────────
cat <<'WARNING'

╔══════════════════════════════════════════════════════════════════════════════╗
║  ⚠  AVERTISSEMENT RESTORE — LISEZ AVANT DE CONTINUER  ⚠                   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Ce script restaure : CA, clés, config.yaml, .env, état DevPod.            ║
║                                                                             ║
║  CE QUI N'EST PAS RESTAURÉ :                                                ║
║  • Les workspaces actifs (ils vivent dans les daemons Docker des nœuds).   ║
║  • Les sessions de travail en cours.                                        ║
║  • Les images Docker buildées sur les nœuds.                               ║
║                                                                             ║
║  APRÈS RESTORE :                                                            ║
║  1. Vérifier que tous les nœuds sont encore enrôlés et accessibles.        ║
║  2. Pour chaque user : relancer ses workspaces via le portail (devpod up). ║
║  3. Les données non sauvegardées dans /data sont perdues.                  ║
║                                                                             ║
║  « backup facile » ≠ « reprise transparente des sessions » (§G-35)         ║
╚══════════════════════════════════════════════════════════════════════════════╝

WARNING

if [[ -t 0 ]]; then
    read -rp "Continuer le restore ? [oui/NON] : " CONFIRM
    if [[ "$CONFIRM" != "oui" ]]; then
        echo "Restore annulé."
        exit 0
    fi
else
    if [[ "${RESTORE_ASSUME_YES:-}" != "1" ]]; then
        echo "ERREUR : stdin non interactif. Relancer avec RESTORE_ASSUME_YES=1 pour confirmer le restore destructif." >&2
        exit 1
    fi
    echo "(Mode non interactif — RESTORE_ASSUME_YES=1, restore confirmé)"
fi

# ── Sauvegarde de l'existant avant restore ────────────────────────────────────
PRE_RESTORE_BACKUP=""
if [[ -d "$DATA_ROOT" ]]; then
    PRE_RESTORE_BACKUP="$(dirname "$DATA_ROOT")/data-pre-restore-$(date -u +%Y%m%d-%H%M%S)"
    echo "==> Sauvegarde de $DATA_ROOT → $PRE_RESTORE_BACKUP (sécurité)"
    cp -a "$DATA_ROOT" "$PRE_RESTORE_BACKUP"
fi

# ── Restore ──────────────────────────────────────────────────────────────────
# Purger la cible pour un restore miroir strict (les orphelins ne persistent pas)
if [[ -d "$DATA_ROOT" ]]; then
    rm -rf "$DATA_ROOT"
fi

echo "==> Déchiffrement et restauration depuis $ARCHIVE..."
PARENT_DIR="$(dirname "$DATA_ROOT")"
age -d -i "$AGE_IDENTITY" "$ARCHIVE" \
    | tar xzf - -C "$PARENT_DIR"

echo ""
echo "==> Restore terminé."
echo ""
echo "Étapes post-restore obligatoires :"
echo "  1. Vérifier que /data/.env est complet (OIDC_CLIENT_SECRET, CF_API_TOKEN, etc.)"
echo "  2. chmod 600 $DATA_ROOT/.env $DATA_ROOT/certs/ca/ca-key.pem"
echo "  3. Redémarrer le portail : docker compose -f deploy/docker-compose.yml up -d"
echo "  4. Vérifier la connectivité aux nœuds enrôlés."
echo "  5. Demander aux utilisateurs de re-lancer leurs workspaces."
echo ""
if [[ -n "$PRE_RESTORE_BACKUP" ]]; then
    echo "En cas de problème, la sauvegarde pré-restore est dans :"
    echo "  $PRE_RESTORE_BACKUP"
fi
