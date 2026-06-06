from __future__ import annotations

import base64
import hashlib

import httpx
import pytest
import respx

from tests.auth.conftest import (
    CLIENT_ID,
    DISCOVERY_DOC,
    ISSUER,
    RSA_KEY,
    TEST_KID,
    make_id_token,
    make_jwks_response,
)

DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
JWKS_URI = DISCOVERY_DOC["jwks_uri"]
TOKEN_ENDPOINT = DISCOVERY_DOC["token_endpoint"]
CLIENT_SECRET = "test-secret"
REDIRECT_URI = "https://portal.test/callback"


@pytest.mark.asyncio
async def test_authorization_url_contains_pkce_and_state() -> None:
    from portal.auth.oidc import OIDCClient

    client = OIDCClient(
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
    )

    with respx.mock:
        respx.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json=DISCOVERY_DOC))
        session: dict = {}
        url = await client.authorization_url(session)

    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url
    assert "state=" in url
    assert "nonce=" in url

    assert "oidc_state" in session
    assert "oidc_nonce" in session
    assert "oidc_verifier" in session

    # Verify PKCE challenge is SHA256(verifier) base64url-encoded
    verifier = session["oidc_verifier"]
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    assert expected_challenge in url


@pytest.mark.asyncio
async def test_exchange_raises_on_state_mismatch() -> None:
    from portal.auth.oidc import OIDCClient, OIDCError

    client = OIDCClient(
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
    )

    with respx.mock:
        respx.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json=DISCOVERY_DOC))
        session: dict = {}
        await client.authorization_url(session)

    with pytest.raises(OIDCError, match="state"):
        await client.exchange_and_validate(
            code="some-code",
            state="WRONG",
            session=session,
        )


@pytest.mark.asyncio
async def test_exchange_validates_id_token_successfully() -> None:
    from portal.auth.oidc import OIDCClient

    client = OIDCClient(
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
    )

    with respx.mock:
        respx.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json=DISCOVERY_DOC))
        session: dict = {}
        await client.authorization_url(session)

    nonce = session["oidc_nonce"]
    id_token = make_id_token(nonce=nonce, username="alice")
    jwks_resp = make_jwks_response()
    token_response = {
        "access_token": "access-token-xyz",
        "token_type": "Bearer",
        "id_token": id_token,
    }

    with respx.mock:
        respx.get(JWKS_URI).mock(return_value=httpx.Response(200, json=jwks_resp))
        respx.post(TOKEN_ENDPOINT).mock(return_value=httpx.Response(200, json=token_response))
        claims = await client.exchange_and_validate(
            code="auth-code-123",
            state=session["oidc_state"],
            session=session,
        )

    assert claims["preferred_username"] == "alice"
    # Session should be cleaned up
    assert "oidc_verifier" not in session
    assert "oidc_nonce" not in session


@pytest.mark.asyncio
async def test_validate_refetches_jwks_on_unknown_kid() -> None:
    from portal.auth.oidc import OIDCClient

    client = OIDCClient(
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
    )

    with respx.mock:
        respx.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json=DISCOVERY_DOC))
        session: dict = {}
        await client.authorization_url(session)

    nonce = session["oidc_nonce"]
    id_token = make_id_token(nonce=nonce, username="alice", kid=TEST_KID, key=RSA_KEY)

    # First JWKS response has a wrong kid — causes InvalidKeyIdError
    wrong_kid_jwks = make_jwks_response(kid="other-kid")
    # Second JWKS response has the correct kid
    correct_jwks = make_jwks_response(kid=TEST_KID)

    token_response = {
        "access_token": "access-token-xyz",
        "token_type": "Bearer",
        "id_token": id_token,
    }

    with respx.mock:
        respx.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json=DISCOVERY_DOC))
        respx.route(method="GET", url=JWKS_URI).side_effect = [
            httpx.Response(200, json=wrong_kid_jwks),
            httpx.Response(200, json=correct_jwks),
        ]
        respx.post(TOKEN_ENDPOINT).mock(return_value=httpx.Response(200, json=token_response))
        claims = await client.exchange_and_validate(
            code="auth-code-123",
            state=session["oidc_state"],
            session=session,
        )
        # Count JWKS calls inside the mock context where respx.calls is populated
        jwks_calls = [call for call in respx.calls if call.request.url.path.endswith("/certs")]

    assert claims["preferred_username"] == "alice"
    # 2 JWKS fetches: first (stale/unknown kid) + refetch
    assert len(jwks_calls) == 2


@pytest.mark.asyncio
async def test_validate_raises_on_expired_token() -> None:
    from portal.auth.oidc import OIDCClient, OIDCError

    client = OIDCClient(
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
    )

    with respx.mock:
        respx.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json=DISCOVERY_DOC))
        session: dict = {}
        await client.authorization_url(session)

    nonce = session["oidc_nonce"]
    # Token expired 1 hour ago
    id_token = make_id_token(nonce=nonce, username="alice", expiry_offset=-3600)
    jwks_resp = make_jwks_response()
    token_response = {
        "access_token": "access-token-xyz",
        "token_type": "Bearer",
        "id_token": id_token,
    }

    with respx.mock:
        respx.get(JWKS_URI).mock(return_value=httpx.Response(200, json=jwks_resp))
        respx.post(TOKEN_ENDPOINT).mock(return_value=httpx.Response(200, json=token_response))
        with pytest.raises(OIDCError, match="[Ee]xpir"):
            await client.exchange_and_validate(
                code="auth-code-123",
                state=session["oidc_state"],
                session=session,
            )
