from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Union

from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

CertType = Literal[
    "ssh-ed25519",
    "ssh-rsa-2048",
    "ssh-rsa-4096",
    "ssh-ecdsa-p256",
    "tls-rsa-2048",
    "tls-rsa-4096",
    "tls-ec-p256",
    "tls-ec-p384",
]

_SSH_TYPES = {"ssh-ed25519", "ssh-rsa-2048", "ssh-rsa-4096", "ssh-ecdsa-p256"}


@dataclass(frozen=True)
class KeyPair:
    public_key: str    # OpenSSH ou PEM SubjectPublicKeyInfo
    private_key_pem: str  # OpenSSH PEM ou PKCS8 PEM (jamais chiffré)


def generate_keypair(cert_type: CertType) -> KeyPair:
    priv: Union[
        ed25519.Ed25519PrivateKey,
        rsa.RSAPrivateKey,
        ec.EllipticCurvePrivateKey,
    ]
    if cert_type == "ssh-ed25519":
        priv = ed25519.Ed25519PrivateKey.generate()
    elif cert_type == "ssh-rsa-2048":
        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    elif cert_type == "ssh-rsa-4096":
        priv = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    elif cert_type == "ssh-ecdsa-p256":
        priv = ec.generate_private_key(ec.SECP256R1())
    elif cert_type == "tls-rsa-2048":
        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    elif cert_type == "tls-rsa-4096":
        priv = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    elif cert_type == "tls-ec-p256":
        priv = ec.generate_private_key(ec.SECP256R1())
    elif cert_type == "tls-ec-p384":
        priv = ec.generate_private_key(ec.SECP384R1())
    else:
        raise ValueError(f"Unknown cert_type: {cert_type}")

    if cert_type in _SSH_TYPES:
        private_pem = priv.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption())
        public_bytes = priv.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)
    else:
        private_pem = priv.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        public_bytes = priv.public_key().public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
        )

    return KeyPair(
        public_key=public_bytes.decode(),
        private_key_pem=private_pem.decode(),
    )
