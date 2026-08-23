#!/usr/bin/env bash
set -euo pipefail

# GitHub Copilot CLI — agent de terminal (@github/copilot), pendant de claude-code.
# Auth = device-flow OAuth AU RUNTIME (`copilot` puis /login) avec la licence
# Copilot du développeur : AUCUN secret injecté, aucun token écrit par la recette.
# L'état/l'auth vivent dans ~/.copilot, persisté hors recette via memory_volume
# (cf. recipe.meta.yaml) — sans quoi il faut refaire /login à chaque recréation.

# Prérequis : Node.js 22+ (exigence de @github/copilot). On vérifie explicitement
# plutôt que d'installer un runtime en aveugle, qui pourrait entrer en conflit
# avec l'image de base. Si Node manque ou est trop vieux, échec franc et lisible.
if ! command -v node >/dev/null 2>&1; then
    echo "ERROR: node introuvable. GitHub Copilot CLI requiert Node.js 22+." >&2
    echo "       Provisionne Node 22+ dans l'image de base avant copilot-cli." >&2
    exit 1
fi
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
if [ "$NODE_MAJOR" -lt 22 ]; then
    echo "ERROR: Node.js v$NODE_MAJOR détecté ; Copilot CLI requiert la version 22+." >&2
    exit 1
fi

npm install -g @github/copilot

echo "==> GitHub Copilot CLI: $(copilot --version 2>/dev/null || echo 'installé')"
echo "==> Auth : lance 'copilot' dans le terminal puis /login (device-flow, licence Copilot)."
