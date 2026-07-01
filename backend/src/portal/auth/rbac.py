from __future__ import annotations

import re
from dataclasses import dataclass, field

import structlog
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..settings import get_settings

_bearer = HTTPBearer(auto_error=False)

_log = structlog.get_logger(__name__)

# Regex username : DNS-safe, max 40 chars, autorise points (LDAP)
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,38}[a-z0-9]$")
_INVALID_CHARS_RE = re.compile(r"[^a-z0-9._-]")
_MULTI_SEP_RE = re.compile(r"[-._]{2,}")


class UsernameError(ValueError):
    """Username non conforme."""


@dataclass
class UserInfo:
    login: str
    roles: list[str] = field(default_factory=list)
    sub: str = ""


def normalize_login(raw: str) -> str:
    """Dérive un login valide depuis un claim brut (email ou username LDAP/OIDC).

    - email → partie locale (avant @)
    - caractères invalides → tiret
    - séparateurs multiples → un seul tiret
    - tronqué à 40 caractères
    """
    candidate = raw.lower()
    if "@" in candidate:
        candidate = candidate.split("@")[0]
    candidate = _INVALID_CHARS_RE.sub("-", candidate)
    candidate = _MULTI_SEP_RE.sub("-", candidate)
    candidate = candidate.strip("-._")[:40].rstrip("-._")
    return candidate


def validate_username(username: str) -> str:
    if not _USERNAME_RE.fullmatch(username):
        raise UsernameError(
            f"username {username!r} does not match ^[a-z0-9][a-z0-9._-]{{0,38}}[a-z0-9]$"
        )
    return username


def extract_roles(claims: dict[str, object], role_claim_path: str) -> list[str]:
    parts = role_claim_path.split(".")
    value: object = claims
    for part in parts:
        if not isinstance(value, dict):
            return []
        value = value.get(part)
        if value is None:
            return []
    if isinstance(value, list):
        return [str(r) for r in value]
    return []


def get_current_user(request: Request) -> UserInfo | None:
    user_data = request.session.get("user")
    if not user_data:
        return None
    return UserInfo(
        login=user_data["login"],
        roles=user_data.get("roles", []),
        sub=user_data.get("sub", ""),
    )


async def require_user(request: Request) -> UserInfo:
    settings = get_settings()
    user = get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    allowed = {settings.oidc_user_role, settings.oidc_admin_role}
    if not set(user.roles) & allowed:
        _log.warning("rbac_denied", login=user.login, roles=user.roles)
        raise HTTPException(status_code=403, detail="Insufficient role")
    return user


async def require_admin_or_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> UserInfo:
    """Accepte soit une session admin (cookie), soit un Bearer token == portal_api_key."""
    settings = get_settings()
    if credentials is not None:
        if settings.portal_api_key and credentials.credentials == settings.portal_api_key:
            return UserInfo(login="__api__", roles=[settings.oidc_admin_role])
        raise HTTPException(status_code=401, detail="Invalid API key")
    return await require_admin(request)


async def require_admin(request: Request) -> UserInfo:
    settings = get_settings()
    user = get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if settings.oidc_admin_role not in user.roles:
        _log.warning("rbac_admin_denied", login=user.login, roles=user.roles)
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
