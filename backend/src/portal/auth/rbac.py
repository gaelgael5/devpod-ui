from __future__ import annotations

import re
from dataclasses import dataclass, field

import structlog
from fastapi import HTTPException, Request

from ..settings import get_settings

_log = structlog.get_logger(__name__)

# Regex username : DNS-safe, max 40 chars, autorise points (LDAP)
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,38}[a-z0-9]$")


class UsernameError(ValueError):
    """Username non conforme."""


@dataclass
class UserInfo:
    login: str
    roles: list[str] = field(default_factory=list)
    sub: str = ""


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
        raise HTTPException(status_code=403, detail="Not authenticated")
    allowed = {settings.oidc_user_role, settings.oidc_admin_role}
    if not set(user.roles) & allowed:
        _log.warning("rbac_denied", login=user.login, roles=user.roles)
        raise HTTPException(status_code=403, detail="Insufficient role")
    return user


async def require_admin(request: Request) -> UserInfo:
    settings = get_settings()
    user = get_current_user(request)
    if user is None:
        raise HTTPException(status_code=403, detail="Not authenticated")
    if settings.oidc_admin_role not in user.roles:
        _log.warning("rbac_admin_denied", login=user.login, roles=user.roles)
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
