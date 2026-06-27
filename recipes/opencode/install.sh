#!/usr/bin/env bash
set -euo pipefail

if ! command -v npm &>/dev/null; then
    echo "ERROR: npm not found. Add the nodejs recipe first." >&2
    exit 1
fi

echo "==> Installing OpenCode CLI"
npm install -g opencode-ai

# Localiser le binaire (nvm, system node, volta…)
OPENCODE_BIN=""
NPM_BIN_DIR="$(npm bin -g 2>/dev/null || true)"
[ -f "${NPM_BIN_DIR}/opencode" ] && OPENCODE_BIN="${NPM_BIN_DIR}/opencode"

if [ -z "$OPENCODE_BIN" ]; then
    PREFIX_BIN="$(npm config get prefix 2>/dev/null)/bin/opencode"
    [ -f "$PREFIX_BIN" ] && OPENCODE_BIN="$PREFIX_BIN"
fi

if [ -z "$OPENCODE_BIN" ]; then
    OPENCODE_BIN="$(command -v opencode 2>/dev/null || true)"
fi

if [ -z "$OPENCODE_BIN" ]; then
    echo "ERROR: opencode binary not found after install — PATH=${PATH}" >&2
    exit 1
fi

echo "==> Found opencode at ${OPENCODE_BIN}"

if [ "$OPENCODE_BIN" != "/usr/local/bin/opencode" ]; then
    cat > /usr/local/bin/opencode <<WRAPPER
#!/usr/bin/env bash
exec "${OPENCODE_BIN}" "\$@"
WRAPPER
    chmod +x /usr/local/bin/opencode
fi

NPM_BIN_PATH="$(dirname "$OPENCODE_BIN")"
cat > /etc/profile.d/opencode-path.sh <<PROFILE
export PATH="\${PATH:+\$PATH:}${NPM_BIN_PATH}"
PROFILE
chmod +x /etc/profile.d/opencode-path.sh

echo "==> OpenCode: $(opencode --version 2>/dev/null || echo 'installed')"
