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
umask 077

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

# ── Extraction dans un répertoire temporaire ────────────────────────────────
PARENT_DIR="$(dirname "$DATA_ROOT")"
RESTORE_TMP=$(mktemp -d -p "$PARENT_DIR" .restore-XXXXXX)
trap 'rm -rf "$RESTORE_TMP"' EXIT

echo "==> Déchiffrement et restauration depuis $ARCHIVE..."
age -d -i "$AGE_IDENTITY" "$ARCHIVE" \
    | tar xzf - -C "$RESTORE_TMP"

RESTORED_DATA="$RESTORE_TMP/$(basename "$DATA_ROOT")"
if [[ ! -d "$RESTORED_DATA" ]]; then
    echo "ERREUR : l'archive ne contient pas de répertoire '$(basename "$DATA_ROOT")' à la racine." >&2
    exit 1
fi

# ── Ré-application des perms sensibles (§E-26, CLAUDE.md) ──────────────────
chmod 700 "$RESTORED_DATA"
[[ -f "$RESTORED_DATA/.env" ]] && chmod 600 "$RESTORED_DATA/.env"
[[ -f "$RESTORED_DATA/secrets.yaml" ]] && chmod 600 "$RESTORED_DATA/secrets.yaml"
find "$RESTORED_DATA/certs" -type d -exec chmod 700 {} + 2>/dev/null || true
[[ -f "$RESTORED_DATA/certs/ca/ca-key.pem" ]] && chmod 600 "$RESTORED_DATA/certs/ca/ca-key.pem"
find "$RESTORED_DATA/users" -type d -exec chmod 700 {} + 2>/dev/null || true

# ── Sauvegarde de l'existant avant bascule ─────────────────────────────────
PRE_RESTORE_BACKUP=""
if [[ -d "$DATA_ROOT" ]]; then
    PRE_RESTORE_BACKUP=$(mktemp -d -p "$PARENT_DIR" data-pre-restore-XXXXXX)
    echo "==> Sauvegarde de $DATA_ROOT → $PRE_RESTORE_BACKUP (sécurité)"
    cp -a "$DATA_ROOT/." "$PRE_RESTORE_BACKUP/"
fi

# ── Bascule atomique ────────────────────────────────────────────────────────
# double-mv : évite la fenêtre où DATA_ROOT est absent entre rm et mv
OLD_DATA=""
if [[ -d "$DATA_ROOT" ]]; then
    OLD_DATA="$PARENT_DIR/.data-old-$$"
    mv "$DATA_ROOT" "$OLD_DATA"
fi
mv "$RESTORED_DATA" "$DATA_ROOT"
trap - EXIT  # annuler le nettoyage du tmp (mv a tout basculé)
[[ -n "$OLD_DATA" ]] && rm -rf "$OLD_DATA"

echo ""
echo "==> Restore terminé."
echo ""
echo "Étapes post-restore obligatoires :"
echo "  1. Vérifier que /data/.env est complet (OIDC_CLIENT_SECRET, CF_API_TOKEN, etc.)"
echo "  2. Vérifier les perms : ls -la $DATA_ROOT/.env $DATA_ROOT/certs/ca/ca-key.pem  (attendu : 600)"
echo "  3. Redémarrer le portail : docker compose -f deploy/docker-compose.yml up -d"
echo "  4. Vérifier la connectivité aux nœuds enrôlés."
echo "  5. Demander aux utilisateurs de re-lancer leurs workspaces."
echo ""
if [[ -n "$PRE_RESTORE_BACKUP" ]]; then
    echo "En cas de problème, la sauvegarde pré-restore est dans :"
    echo "  $PRE_RESTORE_BACKUP"
fi
