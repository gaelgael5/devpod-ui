"""Client OAuth 2.1 de la gateway vers un backend MCP amont (ex. Confluence).

Brique de la Tranche 1 : la logique protocolaire pure (découverte des métadonnées,
enregistrement dynamique DCR, construction de l'URL d'autorisation PKCE, échange
du code et rafraîchissement). Sans état applicatif ni horloge : les fonctions
retournent `expires_in` et laissent l'appelant calculer `expires_at`, ce qui les
rend testables de façon déterministe.

Références : RFC 8414 (metadata AS), RFC 7591 (DCR), RFC 7636 (PKCE),
RFC 9728 (protected resource metadata), RFC 8707 (resource indicators).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
import structlog
from pydantic import BaseModel, ConfigDict

_log = structlog.get_logger(__name__)
_TIMEOUT = httpx.Timeout(15.0)


class OAuthClientError(Exception):
    """Échec du flux OAuth côté client (message sûr, jamais de secret)."""


class DiscoveryError(OAuthClientError):
    pass


class RegistrationError(OAuthClientError):
    pass


class TokenExchangeError(OAuthClientError):
    pass


class ASMetadata(BaseModel):
    """Métadonnées utiles du serveur d'autorisation (extra ignoré)."""

    model_config = ConfigDict(extra="ignore")
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None = None
    scopes_supported: list[str] | None = None


class TokenResponse(BaseModel):
    """Réponse d'un token endpoint (extra ignoré). `expires_in` en secondes."""

    model_config = ConfigDict(extra="ignore")
    access_token: str
    token_type: str = "Bearer"
    refresh_token: str | None = None
    expires_in: int | None = None
    scope: str | None = None


def _origin(url: str) -> str:
    """scheme://host[:port] d'une URL (pour le .well-known de ressource protégée)."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _wellknown(base: str, name: str) -> str:
    return base.rstrip("/") + "/.well-known/" + name


async def _get_json(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    resp = await client.get(url, headers={"Accept": "application/json"})
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise DiscoveryError(f"réponse JSON inattendue (non-objet) depuis {url}")
    return data


async def discover_metadata(mcp_url: str, auth_url: str | None = None) -> ASMetadata:
    """Découvre les métadonnées du serveur d'autorisation d'un backend.

    - `auth_url` renseignée → traitée comme issuer/base de l'AS.
    - sinon → `.well-known/oauth-protected-resource` sur l'origine du MCP donne
      `authorization_servers[0]`, dont on lit ensuite les métadonnées.

    Pour les métadonnées AS : `oauth-authorization-server` puis, à défaut,
    `openid-configuration`.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        issuer = (auth_url or "").strip()
        if not issuer:
            prm_url = _wellknown(_origin(mcp_url), "oauth-protected-resource")
            try:
                prm = await _get_json(client, prm_url)
            except httpx.HTTPError as exc:
                raise DiscoveryError(
                    "métadonnées de ressource protégée introuvables — renseignez l'URL "
                    f"du serveur d'autorisation ({type(exc).__name__})"
                ) from exc
            servers = prm.get("authorization_servers") or []
            if not servers or not isinstance(servers[0], str):
                raise DiscoveryError("aucun authorization_servers annoncé par le backend")
            issuer = servers[0]

        last_exc: Exception | None = None
        for name in ("oauth-authorization-server", "openid-configuration"):
            try:
                meta = await _get_json(client, _wellknown(issuer, name))
            except httpx.HTTPError as exc:
                last_exc = exc
                continue
            try:
                return ASMetadata.model_validate(meta)
            except ValueError as exc:  # champs obligatoires manquants
                raise DiscoveryError(f"métadonnées AS incomplètes : {exc}") from exc
        raise DiscoveryError(
            f"métadonnées du serveur d'autorisation introuvables sur {issuer} "
            f"({type(last_exc).__name__ if last_exc else 'inconnu'})"
        )


async def register_client(
    metadata: ASMetadata, redirect_uri: str, *, client_name: str, scopes: str
) -> tuple[str, str | None]:
    """Enregistrement dynamique (DCR) d'un client public PKCE. Retourne (client_id, secret?).

    `token_endpoint_auth_method=none` : client public, PKCE seul (auth par
    utilisateur, aucun secret partagé nécessaire). Si l'AS émet malgré tout un
    secret, on le remonte pour stockage chiffré.
    """
    if not metadata.registration_endpoint:
        raise RegistrationError(
            "le serveur n'annonce pas de registration_endpoint (DCR indisponible) — "
            "un enregistrement d'application manuel serait nécessaire"
        )
    body = {
        "client_name": client_name,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": scopes,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await client.post(metadata.registration_endpoint, json=body)
    if resp.status_code not in (200, 201):
        raise RegistrationError(f"DCR refusé ({resp.status_code}) : {resp.text[:200]}")
    data = resp.json()
    client_id = data.get("client_id")
    if not client_id:
        raise RegistrationError("réponse DCR sans client_id")
    return client_id, data.get("client_secret")


def build_authorization_url(
    metadata: ASMetadata,
    *,
    client_id: str,
    redirect_uri: str,
    scopes: str,
    state: str,
    code_challenge: str,
    resource: str | None = None,
) -> str:
    """URL d'autorisation (authorization-code + PKCE S256).

    `resource` (RFC 8707) = URI canonique du MCP amont, incluse quand fournie pour
    que le token soit bien émis pour cette ressource.
    """
    params: dict[str, str] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if resource:
        params["resource"] = resource
    sep = "&" if "?" in metadata.authorization_endpoint else "?"
    return metadata.authorization_endpoint + sep + urlencode(params)


async def _token_request(
    metadata: ASMetadata, data: dict[str, str], client_secret: str | None
) -> TokenResponse:
    headers = {"Accept": "application/json"}
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        if client_secret:  # client confidentiel → client_secret_basic
            resp = await client.post(
                metadata.token_endpoint,
                data=data,
                auth=(data["client_id"], client_secret),
                headers=headers,
            )
        else:  # client public PKCE → client_id dans le corps, pas d'auth HTTP
            resp = await client.post(metadata.token_endpoint, data=data, headers=headers)
    if resp.status_code != 200:
        raise TokenExchangeError(f"token endpoint {resp.status_code} : {resp.text[:200]}")
    try:
        return TokenResponse.model_validate(resp.json())
    except ValueError as exc:
        raise TokenExchangeError(f"réponse token invalide : {exc}") from exc


async def exchange_code(
    metadata: ASMetadata,
    *,
    client_id: str,
    client_secret: str | None,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    resource: str | None = None,
) -> TokenResponse:
    """Échange le code d'autorisation contre des tokens (grant authorization_code)."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    if resource:
        data["resource"] = resource
    return await _token_request(metadata, data, client_secret)


async def refresh_token(
    metadata: ASMetadata,
    *,
    client_id: str,
    client_secret: str | None,
    refresh_token: str,
    resource: str | None = None,
) -> TokenResponse:
    """Rafraîchit l'access token via le refresh token (grant refresh_token)."""
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    if resource:
        data["resource"] = resource
    return await _token_request(metadata, data, client_secret)
