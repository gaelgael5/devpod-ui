"""Curation des claims OIDC exposés sur la page profil (jamais le jeton brut)."""

from __future__ import annotations

from portal.auth.router import curate_token_claims


def test_keeps_only_essential_claims() -> None:
    claims = {
        "sub": "abc-123",
        "email": "u@x.org",
        "preferred_username": "gael",
        "name": "Gael",
        "iss": "https://security.yoops.org/realms/yoops",
        "aud": "workspace-portal",
        "exp": 1786300000,
        "iat": 1786290000,
        # bruit à écarter : jamais exposé
        "access_token": "SECRET",
        "at_hash": "xxx",
        "nonce": "n",
    }
    out = curate_token_claims(claims)
    assert set(out) == {"sub", "email", "preferred_username", "name", "iss", "aud", "exp", "iat"}
    assert "access_token" not in out
    assert out["sub"] == "abc-123"
    assert out["exp"] == "1786300000"  # coercé en chaîne


def test_aud_list_is_joined() -> None:
    out = curate_token_claims({"sub": "s", "aud": ["a", "b"]})
    assert out["aud"] == "a, b"


def test_missing_claims_are_omitted() -> None:
    out = curate_token_claims({"sub": "s"})
    assert out == {"sub": "s"}
