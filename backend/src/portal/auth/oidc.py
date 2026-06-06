from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx
import structlog
from joserfc import jwt as jose_jwt
from joserfc.errors import ExpiredTokenError, InvalidKeyIdError, JoseError
from joserfc.jwk import KeySet
from joserfc.jwt import ClaimsOption, JWTClaimsRegistry

from portal.auth.jwks import JWKSCache

_log = structlog.get_logger(__name__)


class OIDCError(Exception):
    """Raised for any OIDC validation or flow error."""


class OIDCClient:
    """Implements the Authorization Code + PKCE flow with ID token validation."""

    def __init__(
        self,
        *,
        issuer: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        leeway: int = 30,
    ) -> None:
        self._issuer = issuer
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._leeway = leeway
        self._discovery: dict[str, str] | None = None
        self._jwks_cache: JWKSCache | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def authorization_url(self, session: dict[str, str]) -> str:
        """Discover endpoints, generate PKCE + state + nonce, store in session.

        Returns the full authorization URL to redirect the browser to.
        """
        discovery = await self._discover()
        auth_endpoint: str = discovery["authorization_endpoint"]

        state = _random_token()
        nonce = _random_token()
        verifier = _random_token(64)
        challenge = _pkce_challenge(verifier)

        session["oidc_state"] = state
        session["oidc_nonce"] = nonce
        session["oidc_verifier"] = verifier

        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "scope": "openid profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return f"{auth_endpoint}?{urlencode(params)}"

    async def exchange_and_validate(
        self,
        *,
        code: str,
        state: str,
        session: dict[str, str],
    ) -> dict[str, object]:
        """Exchange authorization code for tokens and validate the ID token.

        Returns the validated ID token claims dict.
        Cleans up oidc_state / oidc_nonce / oidc_verifier from session on success.
        """
        expected_state: str | None = session.get("oidc_state")
        if not expected_state or state != expected_state:
            raise OIDCError("state mismatch — possible CSRF")

        verifier: str | None = session.get("oidc_verifier")
        nonce: str | None = session.get("oidc_nonce")

        discovery = await self._discover()
        token_endpoint: str = discovery["token_endpoint"]

        id_token_str = await self._fetch_id_token(
            token_endpoint=token_endpoint,
            code=code,
            verifier=verifier or "",
        )

        claims = await self._validate_id_token(id_token_str, nonce=nonce or "")

        # Clean up OIDC session keys — single-use
        for key in ("oidc_state", "oidc_nonce", "oidc_verifier"):
            session.pop(key, None)

        return claims

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _discover(self) -> dict[str, str]:
        """Fetch (and cache for the lifetime of this client) the OIDC discovery doc."""
        if self._discovery is not None:
            return self._discovery

        url = f"{self._issuer}/.well-known/openid-configuration"
        _log.info("oidc_discover", url=url)
        async with httpx.AsyncClient() as http:
            resp = await http.get(url, timeout=10.0)
            resp.raise_for_status()
        self._discovery = resp.json()
        jwks_uri: str = self._discovery["jwks_uri"]
        self._jwks_cache = JWKSCache(jwks_uri)
        _log.info("oidc_discovered", issuer=self._issuer)
        return self._discovery

    async def _fetch_id_token(self, *, token_endpoint: str, code: str, verifier: str) -> str:
        """POST to token endpoint and return the raw id_token string."""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._redirect_uri,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "code_verifier": verifier,
        }
        _log.info("oidc_token_exchange", endpoint=token_endpoint)
        async with httpx.AsyncClient() as http:
            resp = await http.post(token_endpoint, data=data, timeout=15.0)
            resp.raise_for_status()
        payload = resp.json()
        id_token: str | None = payload.get("id_token")
        if not id_token:
            raise OIDCError("token endpoint did not return id_token")
        return id_token

    async def _validate_id_token(self, id_token: str, *, nonce: str) -> dict[str, object]:
        """Decode and validate the ID token JWT.

        On InvalidKeyIdError (unknown kid) the JWKS cache is force-refetched
        and validation is retried once.  Any remaining error is wrapped in
        OIDCError.
        """
        assert self._jwks_cache is not None, "_discover() must be called first"

        keyset = await self._jwks_cache.get_keyset()
        try:
            return self._decode_and_check(id_token, keyset=keyset, nonce=nonce)
        except InvalidKeyIdError:
            _log.info("oidc_unknown_kid_refetch_jwks")
            keyset = await self._jwks_cache.get_keyset(refetch=True)
            try:
                return self._decode_and_check(id_token, keyset=keyset, nonce=nonce)
            except JoseError as exc:
                raise OIDCError(f"ID token invalid after JWKS refetch: {exc}") from exc
        except ExpiredTokenError as exc:
            raise OIDCError(f"ID token expired: {exc}") from exc
        except JoseError as exc:
            raise OIDCError(f"ID token validation failed: {exc}") from exc

    def _decode_and_check(self, id_token: str, *, keyset: KeySet, nonce: str) -> dict[str, object]:
        """Decode the JWT and validate standard + nonce claims.

        Raises joserfc errors directly so the caller can decide whether to retry.
        """
        token = jose_jwt.decode(id_token, keyset, algorithms=["RS256"])

        registry = JWTClaimsRegistry(
            leeway=self._leeway,
            iss=ClaimsOption(essential=True, value=self._issuer),
            aud=ClaimsOption(essential=True, value=self._client_id),
            exp=ClaimsOption(essential=True),
            iat=ClaimsOption(essential=True),
            nonce=ClaimsOption(essential=True, value=nonce),
        )
        registry.validate(token.claims)
        if "iat" not in token.claims:
            raise OIDCError("id_token missing 'iat' claim")
        return dict(token.claims)


# ------------------------------------------------------------------
# Module-level utilities
# ------------------------------------------------------------------


def _random_token(nbytes: int = 32) -> str:
    """Return a URL-safe random token."""
    return secrets.token_urlsafe(nbytes)


def _pkce_challenge(verifier: str) -> str:
    """Compute S256 code_challenge from verifier (RFC 7636)."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
