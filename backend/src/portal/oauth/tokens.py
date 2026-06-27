"""Génération et hachage des secrets OAuth (tokens, codes, client_id)."""
from __future__ import annotations

import hashlib
import secrets


def new_secret(prefix: str) -> str:
    """Secret opaque : prefix + 32 octets base64-url-safe."""
    return prefix + secrets.token_urlsafe(32)


def sha256_hex(value: str) -> str:
    """SHA256 hex — identique à mcp.service.token_hash (un token OAuth est une apikey)."""
    return hashlib.sha256(value.encode()).hexdigest()


def new_client_id() -> str:
    return "mcpc_" + secrets.token_urlsafe(16)
