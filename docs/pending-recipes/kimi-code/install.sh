#!/usr/bin/env bash
set -euo pipefail

# Kimi Code CLI — agent de terminal (@moonshot-ai/kimi-code, commande `kimi`),
# pendant de claude-code / copilot. Auth AU RUNTIME (`kimi` puis /login : OAuth
# Kimi Code ou clé API Moonshot) : AUCUN secret injecté, aucun token écrit par la
# recette. L'état/l'auth vivent dans ~/.kimi-code, persisté hors recette via
# memory_volume (cf. recipe.meta.yaml) — sinon il faut refaire /login à chaque
# recréation.

# Prérequis : Node.js 22.19+ (exigence de @moonshot-ai/kimi-code). Garde explicite
# plutôt qu'installer un runtime en aveugle ; échec franc si absent/trop vieux.
if ! command -v node >/dev/null 2>&1; then
    echo "ERROR: node introuvable. Kimi Code CLI requiert Node.js 22.19+." >&2
    echo "       Provisionne Node 22.19+ dans l'image de base avant kimi-code." >&2
    exit 1
fi
if ! node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit((a>22||(a===22&&b>=19))?0:1)'; then
    echo "ERROR: $(node -v) détecté ; Kimi Code CLI requiert Node.js 22.19+." >&2
    exit 1
fi

npm install -g @moonshot-ai/kimi-code

echo "==> Kimi Code CLI: $(kimi --version 2>/dev/null || echo 'installé')"
echo "==> Auth : lance 'kimi' dans le terminal puis /login (OAuth Kimi Code ou clé API Moonshot)."
