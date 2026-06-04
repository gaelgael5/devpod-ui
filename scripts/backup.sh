#!/usr/bin/env bash
# backup.sh — Sauvegarde chiffrée de /data (§G-36)
# Le backup contient ca-key.pem, clés SSH, secrets inline → chiffrement OBLIGATOIRE.
#
# Pré-requis : age installé (apt-get install age ou https://github.com/FiloSottile/age/releases)
#
# Usage :
#   AGE_RECIPIENT="age1xxx..." BACKUP_DIR=/backup bash scripts/backup.sh
#   AGE_RECIPIENT="age1xxx..." DATA_ROOT=/data  BACKUP_DIR=/backup bash scripts/backup.sh
#
# Variables d'environnement :
#   DATA_ROOT       Racine des données (défaut : /data)
#   BACKUP_DIR      Dossier de destination (défaut : /backup)
#   AGE_RECIPIENT   Clé publique age du destinataire (OBLIGATOIRE)
set -euo pipefail

DATA_ROOT="${DATA_ROOT:-/data}"
BACKUP_DIR="${BACKUP_DIR:-/backup}"

# AGE_RECIPIENT obligatoire — refus explicite (§G-36 : pas de backup en clair)
if [[ -z "${AGE_RECIPIENT:-}" ]]; then
    echo "ERREUR : AGE_RECIPIENT non défini." >&2
    echo "  Générer une paire : age-keygen -o /root/age-backup.key" >&2
    echo "  Puis : export AGE_RECIPIENT=\$(grep 'public key' /root/age-backup.key | awk '{print \$NF}')" >&2
    exit 1
fi

# Vérifier les outils
for cmd in age tar; do
    command -v "$cmd" &>/dev/null || { echo "ERREUR : $cmd introuvable" >&2; exit 1; }
done

mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date -u +%Y%m%d-%H%M%S)
ARCHIVE="$BACKUP_DIR/portal-backup-${TIMESTAMP}.tar.gz.age"

echo "==> Backup de $DATA_ROOT → $ARCHIVE"
echo "    (§G-36 : chiffré avec age pour la clé ${AGE_RECIPIENT:0:20}...)"

# §G-37 : les écritures atomiques garantissent la cohérence des fichiers individuels.
# tar + age en pipe — aucun fichier intermédiaire en clair sur disque
tar czf - -C "$(dirname "$DATA_ROOT")" "$(basename "$DATA_ROOT")" \
    | age -r "$AGE_RECIPIENT" -o "$ARCHIVE"

ARCHIVE_SIZE=$(du -sh "$ARCHIVE" | cut -f1)
echo "==> Backup terminé : $ARCHIVE ($ARCHIVE_SIZE)"
echo ""
echo "IMPORTANT : ce backup contient ca-key.pem et les secrets inline."
echo "Stocker $ARCHIVE dans un endroit sûr, distinct du serveur."
