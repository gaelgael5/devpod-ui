"""Bastion SSH : accès Termix → workspace via `devpod ssh` (ForceCommand).

Le portail expose un sshd bastion (image portail). Chaque workspace a **une clé
dédiée** : la clé publique est posée dans `authorized_keys` avec un
`command="ws-bastion <login> <ws_id>"` (une ligne par workspace → l'autorisation
est implicite, la clé ne peut atteindre QUE son workspace, aucun resolver requis).
La clé privée est confiée à Termix (credential) et stockée en secret système pour
l'idempotence au recreate.
"""

from __future__ import annotations

from .authorized_keys import remove_entry, set_entry
from .keys import generate_keypair

__all__ = ["generate_keypair", "set_entry", "remove_entry"]
