from __future__ import annotations

import os
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_PBKDF2_ITERATIONS = 600_000
_NONCE_SIZE = 12


class InvalidKey(Exception):
    """Clé incorrecte — déchiffrement AES-GCM échoué."""


def generate_master_key() -> bytes:
    return os.urandom(32)


def generate_salt() -> bytes:
    return os.urandom(16)


def generate_recovery_code() -> str:
    raw = secrets.token_hex(12)  # 24 chars hex = 96 bits
    return "-".join(raw[i : i + 4] for i in range(0, 24, 4))


def derive_wrap_key(pin: str, pin_salt: bytes, kek_env: bytes) -> bytes:
    pbkdf2 = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=pin_salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    pin_derived = pbkdf2.derive(pin.encode())
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=kek_env,
        info=b"vault-wrap-key",
    )
    return hkdf.derive(pin_derived)


def _aes_encrypt(plaintext: bytes, key: bytes) -> bytes:
    nonce = os.urandom(_NONCE_SIZE)
    ct = AESGCM(key).encrypt(nonce, plaintext, None)
    return nonce + ct


def _aes_decrypt(blob: bytes, key: bytes) -> bytes:
    nonce, ct = blob[:_NONCE_SIZE], blob[_NONCE_SIZE:]
    try:
        return AESGCM(key).decrypt(nonce, ct, None)
    except InvalidTag as exc:
        raise InvalidKey("AES-GCM decryption failed") from exc


def encrypt_master_key(master_key: bytes, wrap_key: bytes) -> bytes:
    return _aes_encrypt(master_key, wrap_key)


def decrypt_master_key(encrypted: bytes, wrap_key: bytes) -> bytes:
    return _aes_decrypt(encrypted, wrap_key)


def encrypt_token(token: str, master_key: bytes) -> bytes:
    return _aes_encrypt(token.encode(), master_key)


def decrypt_token(encrypted: bytes, master_key: bytes) -> str:
    return _aes_decrypt(encrypted, master_key).decode()
