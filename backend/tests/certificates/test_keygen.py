from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
    load_ssh_private_key,
    load_ssh_public_key,
)

from portal.certificates.keygen import CertType, generate_keypair


@pytest.mark.parametrize("cert_type", [
    "ssh-ed25519", "ssh-rsa-2048", "ssh-rsa-4096", "ssh-ecdsa-p256",
])
def test_ssh_keypair_roundtrip(cert_type: CertType):
    kp = generate_keypair(cert_type)
    # OpenSSH format: ssh-* for Ed25519/RSA, ecdsa-sha2-* for ECDSA
    assert kp.public_key.startswith(("ssh-", "ecdsa-sha2-"))
    priv = load_ssh_private_key(kp.private_key_pem.encode(), password=None)
    pub = load_ssh_public_key(kp.public_key.encode())
    assert priv.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH) \
           == pub.public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)


@pytest.mark.parametrize("cert_type,expected_cls", [
    ("ssh-ed25519", ed25519.Ed25519PrivateKey),
    ("ssh-rsa-2048", rsa.RSAPrivateKey),
    ("ssh-rsa-4096", rsa.RSAPrivateKey),
    ("ssh-ecdsa-p256", ec.EllipticCurvePrivateKey),
])
def test_ssh_key_type(cert_type: CertType, expected_cls):
    kp = generate_keypair(cert_type)
    priv = load_ssh_private_key(kp.private_key_pem.encode(), password=None)
    assert isinstance(priv, expected_cls)


@pytest.mark.parametrize("cert_type", [
    "tls-rsa-2048", "tls-rsa-4096", "tls-ec-p256", "tls-ec-p384",
])
def test_tls_keypair_pem(cert_type: CertType):
    kp = generate_keypair(cert_type)
    assert "BEGIN PRIVATE KEY" in kp.private_key_pem
    assert "BEGIN PUBLIC KEY" in kp.public_key
    load_pem_private_key(kp.private_key_pem.encode(), password=None)


def test_rsa_2048_key_size():
    kp = generate_keypair("ssh-rsa-2048")
    priv = load_ssh_private_key(kp.private_key_pem.encode(), password=None)
    assert priv.key_size == 2048


def test_rsa_4096_key_size():
    kp = generate_keypair("ssh-rsa-4096")
    priv = load_ssh_private_key(kp.private_key_pem.encode(), password=None)
    assert priv.key_size == 4096
