# name: Python 3.12
# description: Installe Python 3.12 et pip via pyenv
# version: 1.0.0
#!/usr/bin/env bash
set -e
echo "Installing Python 3.12 via pyenv..."
export PYENV_ROOT="$HOME/.pyenv"
curl -fsSL https://pyenv.run | bash
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
pyenv install 3.12
pyenv global 3.12
pip install --upgrade pip
echo "Python $(python --version) installed."
