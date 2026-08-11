"""Génération de paires de clés SSH ed25519 au format OpenSSH (bastion)."""

from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate_keypair(comment: str = "") -> tuple[str, str]:
    """Retourne `(clé_privée_openssh, clé_publique_openssh)`.

    La privée sert de credential Termix ; la publique est posée dans
    `authorized_keys` du bastion. `comment` (ex. le ws_id) annote la clé publique.
    """
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
        .decode()
    )
    if comment:
        public = f"{public} {comment}"
    return private, public
