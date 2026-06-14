# name: Node.js LTS
# description: Installe Node.js LTS via nvm dans le workspace
# version: 1.0.0
#!/usr/bin/env bash
set -e
echo "Installing Node.js LTS via nvm..."
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
mkdir -p "$NVM_DIR"
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
# shellcheck disable=SC1090
source "$NVM_DIR/nvm.sh"
nvm install --lts
nvm alias default node
echo "Node.js $(node --version) installed."
