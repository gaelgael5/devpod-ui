#!/usr/bin/env bash
set -euo pipefail

if ! command -v npm &>/dev/null; then
    echo "ERROR: npm not found. Add the nodejs recipe first." >&2
    exit 1
fi

echo "==> Installing Gemini CLI"
npm install -g @google/gemini-cli

# Localiser le binaire (nvm, system node, volta…)
GEMINI_BIN=""
NPM_BIN_DIR="$(npm bin -g 2>/dev/null || true)"
[ -f "${NPM_BIN_DIR}/gemini" ] && GEMINI_BIN="${NPM_BIN_DIR}/gemini"

if [ -z "$GEMINI_BIN" ]; then
    PREFIX_BIN="$(npm config get prefix 2>/dev/null)/bin/gemini"
    [ -f "$PREFIX_BIN" ] && GEMINI_BIN="$PREFIX_BIN"
fi

if [ -z "$GEMINI_BIN" ]; then
    GEMINI_BIN="$(command -v gemini 2>/dev/null || true)"
fi

if [ -z "$GEMINI_BIN" ]; then
    echo "ERROR: gemini binary not found after install — PATH=${PATH}" >&2
    exit 1
fi

echo "==> Found gemini at ${GEMINI_BIN}"

if [ "$GEMINI_BIN" != "/usr/local/bin/gemini" ]; then
    cat > /usr/local/bin/gemini <<WRAPPER
#!/usr/bin/env bash
exec "${GEMINI_BIN}" "\$@"
WRAPPER
    chmod +x /usr/local/bin/gemini
fi

NPM_BIN_PATH="$(dirname "$GEMINI_BIN")"
cat > /etc/profile.d/gemini-cli-path.sh <<PROFILE
export PATH="\${PATH:+\$PATH:}${NPM_BIN_PATH}"
PROFILE
chmod +x /etc/profile.d/gemini-cli-path.sh

echo "==> Gemini CLI: $(gemini --version 2>/dev/null || echo 'installed')"
