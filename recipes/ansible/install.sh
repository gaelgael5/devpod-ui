#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "==> Installation d'Ansible + ansible-lint dans /opt/ansible"

apt-get update -q
apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv sshpass ca-certificates

python3 -m venv /opt/ansible
/opt/ansible/bin/pip install --no-cache-dir ansible ansible-lint

for bin in ansible ansible-lint ansible-playbook ansible-galaxy ansible-vault; do
    ln -sf "/opt/ansible/bin/${bin}" "/usr/local/bin/${bin}"
done

echo "==> $(ansible --version | head -1)"
echo "==> ansible-lint : $(ansible-lint --version | head -1)"
