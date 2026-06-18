#!/usr/bin/env bash
set -euo pipefail

if ! command -v npm &>/dev/null; then
    echo "ERROR: npm not found. Add the nodejs recipe first." >&2
    exit 1
fi

echo "==> Installing Claude Code CLI"
npm install -g @anthropic-ai/claude-code

# 1. Chercher le binaire fraîchement installé
CLAUDE_BIN=""

# Priorité 1 : npm bin -g (disponible sur npm >=8)
NPM_BIN_DIR="$(npm bin -g 2>/dev/null || true)"
if [ -f "${NPM_BIN_DIR}/claude" ]; then
    CLAUDE_BIN="${NPM_BIN_DIR}/claude"
fi

# Priorité 2 : prefix/bin (nvm, system node…)
if [ -z "$CLAUDE_BIN" ]; then
    PREFIX_BIN="$(npm config get prefix 2>/dev/null)/bin/claude"
    [ -f "$PREFIX_BIN" ] && CLAUDE_BIN="$PREFIX_BIN"
fi

# Priorité 3 : which (si le bin est déjà dans PATH)
if [ -z "$CLAUDE_BIN" ]; then
    CLAUDE_BIN="$(command -v claude 2>/dev/null || true)"
fi

if [ -z "$CLAUDE_BIN" ]; then
    echo "ERROR: claude binary not found after install — PATH=$(echo "$PATH")" >&2
    exit 1
fi

echo "==> Found claude at ${CLAUDE_BIN}"

# 2. Exposer /usr/local/bin/claude (toujours dans PATH, indépendant de nvm)
#    On écrit un wrapper plutôt qu'un symlink : résiste aux changements de version nvm.
if [ "$CLAUDE_BIN" != "/usr/local/bin/claude" ]; then
    cat > /usr/local/bin/claude <<WRAPPER
#!/usr/bin/env bash
exec "${CLAUDE_BIN}" "\$@"
WRAPPER
    chmod +x /usr/local/bin/claude
fi

# 3. Ajouter le répertoire npm bin dans le PATH système (profile.d)
NPM_BIN_PATH="$(dirname "$CLAUDE_BIN")"
PROFILE_D="/etc/profile.d/claude-code-path.sh"
cat > "$PROFILE_D" <<PROFILE
# Added by claude-code devcontainer recipe
export PATH="\${PATH:+\$PATH:}${NPM_BIN_PATH}"
PROFILE
chmod +x "$PROFILE_D"

echo "==> Claude Code: $(claude --version 2>/dev/null || echo 'installed')"
