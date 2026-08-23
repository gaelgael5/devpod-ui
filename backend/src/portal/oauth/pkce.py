"""PKCE S256 (RFC 7636) : génération (côté client) et vérification (côté serveur)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


def _b64url_nopad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def challenge_s256(verifier: str) -> str:
    """`base64url(sha256(verifier))` sans padding — le code_challenge S256."""
    return _b64url_nopad(hashlib.sha256(verifier.encode("ascii")).digest())


def generate_pkce() -> tuple[str, str]:
    """Retourne `(code_verifier, code_challenge)` pour un flux authorization-code.

    Verifier = 43 caractères base64url (256 bits d'entropie, borne haute RFC 7636).
    """
    verifier = _b64url_nopad(secrets.token_bytes(32))
    return verifier, challenge_s256(verifier)


def verify_s256(verifier: str, challenge: str) -> bool:
    """True si `base64url(sha256(verifier))` (sans padding) == `challenge`.

    Comparaison en temps constant. Verifier/challenge vide → False (deny-by-default).
    """
    if not verifier or not challenge:
        return False
    computed = _b64url_nopad(hashlib.sha256(verifier.encode("ascii")).digest())
    return hmac.compare_digest(computed, challenge)
