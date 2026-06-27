#!/usr/bin/env bash
set -euo pipefail

COMPILER="${COMPILER:-gcc}"
export DEBIAN_FRONTEND=noninteractive

echo "==> Installation de l'environnement C/C++ (compilateur : ${COMPILER})"

apt-get update -q
apt-get install -y --no-install-recommends \
    build-essential cmake make ninja-build gdb pkg-config \
    ca-certificates

if [ "$COMPILER" = "clang" ]; then
    apt-get install -y --no-install-recommends \
        clang clang-format clang-tidy lld lldb
    update-alternatives --install /usr/bin/cc  cc  /usr/bin/clang   100
    update-alternatives --install /usr/bin/c++ c++ /usr/bin/clang++ 100
    echo "==> Clang : $(clang --version | head -1)"
fi

echo "==> GCC   : $(gcc --version | head -1)"
echo "==> cmake : $(cmake --version | head -1)"
