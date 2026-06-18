#!/usr/bin/env bash
set -euo pipefail

if ! command -v npm &>/dev/null; then
    echo "ERROR: npm not found. Add the nodejs recipe first." >&2
    exit 1
fi

echo "==> Installing OpenAI Codex CLI"
npm install -g @openai/codex

# Localiser le binaire (nvm, system node, volta…)
CODEX_BIN=""
NPM_BIN_DIR="$(npm bin -g 2>/dev/null || true)"
[ -f "${NPM_BIN_DIR}/codex" ] && CODEX_BIN="${NPM_BIN_DIR}/codex"

if [ -z "$CODEX_BIN" ]; then
    PREFIX_BIN="$(npm config get prefix 2>/dev/null)/bin/codex"
    [ -f "$PREFIX_BIN" ] && CODEX_BIN="$PREFIX_BIN"
fi

if [ -z "$CODEX_BIN" ]; then
    CODEX_BIN="$(command -v codex 2>/dev/null || true)"
fi

if [ -z "$CODEX_BIN" ]; then
    echo "ERROR: codex binary not found after install — PATH=${PATH}" >&2
    exit 1
fi

echo "==> Found codex at ${CODEX_BIN}"

if [ "$CODEX_BIN" != "/usr/local/bin/codex" ]; then
    cat > /usr/local/bin/codex <<WRAPPER
#!/usr/bin/env bash
exec "${CODEX_BIN}" "\$@"
WRAPPER
    chmod +x /usr/local/bin/codex
fi

NPM_BIN_PATH="$(dirname "$CODEX_BIN")"
cat > /etc/profile.d/codex-path.sh <<PROFILE
export PATH="\${PATH:+\$PATH:}${NPM_BIN_PATH}"
PROFILE
chmod +x /etc/profile.d/codex-path.sh

echo "==> Codex: $(codex --version 2>/dev/null || echo 'installed')"
