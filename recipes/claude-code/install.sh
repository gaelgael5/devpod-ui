#!/usr/bin/env bash
set -euo pipefail

if ! command -v npm &>/dev/null; then
    echo "ERROR: npm not found. Add the nodejs recipe first." >&2
    exit 1
fi

echo "==> Installing Claude Code CLI"
npm install -g @anthropic-ai/claude-code

# 1. Localiser le binaire fraîchement installé
CLAUDE_BIN=""

# Priorité 1 : prefix global npm (remplace `npm bin -g`, supprimé en npm 9+)
NPM_BIN_DIR="$(npm prefix -g 2>/dev/null)/bin"
if [ -f "${NPM_BIN_DIR}/claude" ]; then
    CLAUDE_BIN="${NPM_BIN_DIR}/claude"
fi

# Priorité 2 : claude déjà présent dans le PATH
if [ -z "$CLAUDE_BIN" ]; then
    CLAUDE_BIN="$(command -v claude 2>/dev/null || true)"
fi

if [ -z "$CLAUDE_BIN" ]; then
    echo "ERROR: claude binary not found after install — PATH=$PATH" >&2
    exit 1
fi

echo "==> Found claude at ${CLAUDE_BIN}"

# 2. Exposer /usr/local/bin/claude (toujours dans le PATH, indépendant de nvm)
#    Wrapper plutôt que symlink : résiste aux changements de version nvm.
if [ "$CLAUDE_BIN" != "/usr/local/bin/claude" ]; then
    cat > /usr/local/bin/claude <<WRAPPER
#!/usr/bin/env bash
exec "${CLAUDE_BIN}" "\$@"
WRAPPER
    chmod +x /usr/local/bin/claude
fi

# 3. Ajouter le répertoire npm bin au PATH système (profile.d)
NPM_BIN_PATH="$(dirname "$CLAUDE_BIN")"
PROFILE_D="/etc/profile.d/claude-code-path.sh"
cat > "$PROFILE_D" <<PROFILE
# Added by claude-code devcontainer recipe
export PATH="\${PATH:+\$PATH:}${NPM_BIN_PATH}"
PROFILE
chmod +x "$PROFILE_D"

# 4. Vérification de version NON-BLOQUANTE
#    </dev/null  : coupe stdin → pas d'attente sur l'onboarding interactif (premier run)
#    timeout 15  : borne tout appel réseau résiduel (auto-update, etc.)
#    DISABLE_... : neutralise le trafic non-essentiel au build
#    || echo     : filet si le binaire ne répond pas comme attendu
CLAUDE_VERSION="$(CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 timeout 15 claude --version </dev/null 2>/dev/null || echo 'installed')"
echo "==> Claude Code: ${CLAUDE_VERSION}"