from __future__ import annotations

import structlog
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .. import settings as _settings_module
from ..vault.crypto import decrypt_token, encrypt_token

log = structlog.get_logger(__name__)


class KekUnavailable(Exception):
    """PORTAL_VAULT_KEK absent : impossible de chiffrer/déchiffrer une clé de service."""


def _derive_kek() -> bytes:
    kek_hex = _settings_module.get_settings().portal_vault_kek
    if not kek_hex:
        log.warning("mcp_kek_unavailable")
        raise KekUnavailable("PORTAL_VAULT_KEK non configuré")
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"mcp-backend-key-v1",
    )
    return hkdf.derive(bytes.fromhex(kek_hex))


def encrypt_service_key(plaintext: str) -> bytes:
    return encrypt_token(plaintext, _derive_kek())


def decrypt_service_key(blob: bytes) -> str:
    return decrypt_token(blob, _derive_kek())
