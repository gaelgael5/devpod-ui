# backend/tests/oauth/test_pkce.py
from __future__ import annotations

import base64
import hashlib

from portal.oauth.pkce import verify_s256


def _challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def test_valid_verifier() -> None:
    v = "a" * 64
    assert verify_s256(v, _challenge(v)) is True


def test_wrong_challenge() -> None:
    v = "a" * 64
    assert verify_s256(v, _challenge("b" * 64)) is False


def test_empty_inputs() -> None:
    assert verify_s256("", "x") is False
    assert verify_s256("x", "") is False
