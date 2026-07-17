from __future__ import annotations

import hmac
import re
import time
from collections.abc import Mapping
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


def session_within_max_age(session: Mapping[str, object]) -> bool:
    """True si la session respecte le plafond d'âge ABSOLU depuis le login (bug 032).

    Les rôles étant figés dans le cookie au login, une session ne peut vivre au-delà
    de `session_absolute_max_age` secondes depuis son `auth_time`. Ce plafond est
    DÉCOUPLÉ de l'inactivité : l'idle glissant est géré par le max_age du cookie
    Starlette (`session_max_age`, réémis à chaque réponse). Le plafond absolu, plus
    large, ne sert qu'à forcer un re-login OIDC périodique (refresh des rôles après
    révocation Keycloak) sans couper un utilisateur actif. Fail-closed : `auth_time`
    absent (cookie legacy) = expiré.

    Partagé entre `get_current_user` (deps RBAC) et les proxies openvscode/SSH qui
    lisent la session hors du dep RBAC : ces derniers DOIVENT aussi appliquer le
    plafond, sinon l'accès VS Code/SSH survivrait à l'expiration (fail-closed).
    """
    from ..config.store import effective_session_absolute_max_age

    auth_time = session.get("auth_time")
    if not isinstance(auth_time, int):
        return False
    return int(time.time()) - auth_time <= effective_session_absolute_max_age()


def get_current_user(request: Request) -> UserInfo | None:
    """Utilisateur courant depuis la session, ou None si absent/expiré.

    À l'expiration du plafond d'âge absolu (bug 032) on renvoie None → 401/403 →
    re-login OIDC → rôles rafraîchis depuis l'IdP.
    """
    user_data = request.session.get("user")
    if not user_data:
        return None
    if not session_within_max_age(request.session):
        _log.info(
            "session_expired_absolute",
            login=user_data.get("login"),
            auth_time=request.session.get("auth_time"),
            max_age_s=get_settings().session_max_age,
        )
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
        if settings.portal_api_key and hmac.compare_digest(
            credentials.credentials, settings.portal_api_key
        ):
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
