"""Vérification PKCE S256 (RFC 7636)."""
from __future__ import annotations

import base64
import hashlib
import hmac


def _b64url_nopad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def verify_s256(verifier: str, challenge: str) -> bool:
    """True si `base64url(sha256(verifier))` (sans padding) == `challenge`.

    Comparaison en temps constant. Verifier/challenge vide → False (deny-by-default).
    """
    if not verifier or not challenge:
        return False
    computed = _b64url_nopad(hashlib.sha256(verifier.encode("ascii")).digest())
    return hmac.compare_digest(computed, challenge)
