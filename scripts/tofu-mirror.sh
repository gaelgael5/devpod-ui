#!/usr/bin/env bash
# tofu-mirror.sh — Peuple le miroir local de providers OpenTofu (ticket 8).
#
# En conditions nominales, un provisionnement ne télécharge RIEN : la config
# CLI générée par le portail exclut la source `direct` et n'autorise que le
# miroir. Ce script se joue à l'installation du portail et à chaque ajout de
# module (nouveau provider), jamais pendant un provisionnement.
#
# Usage :
#   bash tofu-mirror.sh [--mirror /data/tofu/mirror] [--modules deploy/tofu-modules]
#
# Parcourt chaque module (répertoire contenant du .tf) et exécute
# `tofu providers mirror` vers le miroir. Idempotent : les providers déjà
# présents ne sont pas retéléchargés.

set -euo pipefail
IFS=$'\n\t'

MIRROR="/data/tofu/mirror"
MODULES_DIR="deploy/tofu-modules"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mirror)  MIRROR="$2";      shift 2 ;;
        --modules) MODULES_DIR="$2"; shift 2 ;;
        *) echo "ERREUR : option inconnue : $1" >&2
           echo "Options : --mirror --modules" >&2
           exit 1 ;;
    esac
done

command -v tofu >/dev/null || { echo "ERREUR : binaire tofu introuvable." >&2; exit 1; }
[[ -d "$MODULES_DIR" ]] || { echo "ERREUR : répertoire de modules introuvable : $MODULES_DIR" >&2; exit 1; }

mkdir -p "$MIRROR"

TROUVES=0
for module in "$MODULES_DIR"/*/; do
    compgen -G "${module}*.tf" >/dev/null || continue
    TROUVES=$(( TROUVES + 1 ))
    echo "==> Miroir des providers du module $(basename "$module")..."
    # `providers mirror` lit les required_providers du module ; le backend
    # n'est pas contacté (aucun secret nécessaire ici).
    (cd "$module" && tofu providers mirror "$MIRROR")
done

if [[ "$TROUVES" -eq 0 ]]; then
    echo "AVERTISSEMENT : aucun module .tf sous $MODULES_DIR — miroir inchangé." >&2
    exit 0
fi

echo ""
echo "Miroir à jour : $MIRROR"
find "$MIRROR" -name "*.zip" | sed 's/^/    /'
