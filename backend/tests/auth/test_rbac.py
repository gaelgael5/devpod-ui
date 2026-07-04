from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException


def _make_request(session: dict) -> MagicMock:
    req = MagicMock()
    req.session = session
    return req


def _fresh_session(user: dict) -> dict:
    """Session valide : user + auth_time récent (plafond absolu non atteint, bug 032)."""
    return {"user": user, "auth_time": int(time.time())}


def test_get_current_user_returns_none_when_no_session() -> None:
    from portal.auth.rbac import get_current_user

    req = _make_request({})
    assert get_current_user(req) is None


def test_get_current_user_returns_userinfo_from_session() -> None:
    from portal.auth.rbac import UserInfo, get_current_user

    req = _make_request(_fresh_session({"login": "alice", "roles": ["dev"]}))
    user = get_current_user(req)
    assert isinstance(user, UserInfo)
    assert user.login == "alice"
    assert "dev" in user.roles


@pytest.mark.asyncio
async def test_require_user_raises_401_when_no_session() -> None:
    from portal.auth.rbac import require_user

    req = _make_request({})
    with pytest.raises(HTTPException) as exc_info:
        await require_user(req)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_require_user_passes_for_dev_role() -> None:
    from portal.auth.rbac import UserInfo, require_user

    req = _make_request(_fresh_session({"login": "alice", "roles": ["dev"]}))
    user = await require_user(req)
    assert isinstance(user, UserInfo)


@pytest.mark.asyncio
async def test_require_admin_raises_403_for_dev_role() -> None:
    from portal.auth.rbac import require_admin

    req = _make_request(_fresh_session({"login": "alice", "roles": ["dev"]}))
    with pytest.raises(HTTPException) as exc_info:
        await require_admin(req)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_admin_passes_for_admin_role() -> None:
    from portal.auth.rbac import UserInfo, require_admin

    req = _make_request(_fresh_session({"login": "bob", "roles": ["admin"]}))
    user = await require_admin(req)
    assert isinstance(user, UserInfo)


@pytest.mark.asyncio
async def test_require_admin_or_api_key_accepts_matching_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.security import HTTPAuthorizationCredentials

    import portal.auth.rbac as rbac_mod
    from portal.auth.rbac import UserInfo, require_admin_or_api_key

    monkeypatch.setattr(
        rbac_mod,
        "get_settings",
        lambda: type("S", (), {"portal_api_key": "secret-key", "oidc_admin_role": "admin"})(),
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="secret-key")
    user = await require_admin_or_api_key(_make_request({}), creds)
    assert isinstance(user, UserInfo)
    assert user.login == "__api__"
    assert "admin" in user.roles


@pytest.mark.asyncio
async def test_require_admin_or_api_key_rejects_wrong_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.security import HTTPAuthorizationCredentials

    import portal.auth.rbac as rbac_mod
    from portal.auth.rbac import require_admin_or_api_key

    monkeypatch.setattr(
        rbac_mod,
        "get_settings",
        lambda: type("S", (), {"portal_api_key": "secret-key", "oidc_admin_role": "admin"})(),
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong-key")
    with pytest.raises(HTTPException) as exc_info:
        await require_admin_or_api_key(_make_request({}), creds)
    assert exc_info.value.status_code == 401


def test_extract_roles_from_nested_claim() -> None:
    from portal.auth.rbac import extract_roles

    claims = {"realm_access": {"roles": ["dev", "admin"]}}
    assert extract_roles(claims, "realm_access.roles") == ["dev", "admin"]


def test_extract_roles_returns_empty_on_missing_path() -> None:
    from portal.auth.rbac import extract_roles

    assert extract_roles({}, "realm_access.roles") == []


def test_validate_username_accepts_valid() -> None:
    from portal.auth.rbac import validate_username

    assert validate_username("alice") == "alice"
    assert validate_username("alice123") == "alice123"
    assert validate_username("bobsmith") == "bobsmith"


def test_validate_username_rejects_uppercase() -> None:
    from portal.auth.rbac import UsernameError, validate_username

    with pytest.raises(UsernameError):
        validate_username("Alice")


def test_validate_username_rejects_path_traversal() -> None:
    from portal.auth.rbac import UsernameError, validate_username

    with pytest.raises(UsernameError):
        validate_username("../etc")


def test_validate_username_rejects_too_short() -> None:
    from portal.auth.rbac import UsernameError, validate_username

    with pytest.raises(UsernameError):
        validate_username("a")  # 1 char seulement
