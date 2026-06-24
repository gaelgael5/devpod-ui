"""Init SSH d'une VM de test (lot E) : clé du container + login/mot de passe root.

Parties pures (génération du mot de passe, scripts shell) testables ; l'orchestration
SSH multi-hop (container, puis PVE → VM) n'est exerçable que sur serveur.
"""
from __future__ import annotations

import secrets
import shlex

# Lue/générée dans le container : la privée ne quitte jamais le container.
CONTAINER_KEYGEN_CMD = (
    "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
    "([ -f ~/.ssh/id_ed25519 ] || ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519 -q) && "
    "cat ~/.ssh/id_ed25519.pub"
)


def generate_root_password(nbytes: int = 12) -> str:
    """Mot de passe aléatoire URL-safe (alphabet [A-Za-z0-9_-])."""
    return secrets.token_urlsafe(nbytes)


def build_vm_root_inject_script(pubkey: str, password: str, vm_address: str) -> str:
    """Script exécuté sur le nœud PVE (`bash -s`) : SSH vers la VM puis, via `sudo`,
    installe la pubkey du container dans /root/.ssh/authorized_keys et définit le mot
    de passe root.

    `vm_address` = `ciuser@ip` (le compte cloud-init, qui dispose de sudo).
    """
    pub_q = shlex.quote(pubkey)
    creds_q = shlex.quote(f"root:{password}")
    inner = (
        "set -euo pipefail; "
        "sudo mkdir -p /root/.ssh && sudo chmod 700 /root/.ssh && "
        f"(sudo grep -qxF {pub_q} /root/.ssh/authorized_keys 2>/dev/null || "
        f"echo {pub_q} | sudo tee -a /root/.ssh/authorized_keys >/dev/null) && "
        "sudo chmod 600 /root/.ssh/authorized_keys && "
        f"echo {creds_q} | sudo chpasswd"
    )
    return (
        "set -euo pipefail\n"
        "ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=15 "
        f"{shlex.quote(vm_address)} {shlex.quote(inner)}\n"
    )
