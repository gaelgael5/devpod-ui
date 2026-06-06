from __future__ import annotations

import time

from joserfc import jwt as jose_jwt
from joserfc.jwk import RSAKey

RSA_KEY: RSAKey = RSAKey.generate_key(2048)
TEST_KID = "test-key-id"
ISSUER = "https://kc.test/realms/yoops"
CLIENT_ID = "workspace-portal"
DISCOVERY_DOC = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
    "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
    "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
    "response_types_supported": ["code"],
}


def make_jwks_response(key: RSAKey = RSA_KEY, kid: str = TEST_KID) -> dict:  # type: ignore[assignment]
    """Retourne un dict JWKS avec la clé publique."""
    pub = key.as_dict(private=False)
    pub["kid"] = kid
    pub["use"] = "sig"
    pub["alg"] = "RS256"
    return {"keys": [pub]}


def make_id_token(
    *,
    issuer: str = ISSUER,
    client_id: str = CLIENT_ID,
    subject: str = "user-sub-123",
    username: str = "alice",
    roles: list[str] | None = None,
    nonce: str = "test-nonce",
    expiry_offset: int = 300,
    kid: str = TEST_KID,
    key: RSAKey = RSA_KEY,  # type: ignore[assignment]
) -> str:
    """Signe un ID token avec la clé RSA de test."""
    now = int(time.time())
    payload = {
        "iss": issuer,
        "aud": client_id,
        "sub": subject,
        "iat": now,
        "exp": now + expiry_offset,
        "nonce": nonce,
        "preferred_username": username,
        "realm_access": {"roles": roles or ["dev"]},
    }
    headers = {"alg": "RS256", "kid": kid}
    return jose_jwt.encode(headers, payload, key)
