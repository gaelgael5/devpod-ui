# backend/tests/test_caddy_verify.py
"""Forward_auth /auth/caddy/verify : sans session → redirige vers le login (UX),
rôle insuffisant → 403, session valide → 200. Fail-closed §F-33 préservé."""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from portal.auth import router as auth_router


def _settings() -> Mock:
    s = Mock()
    s.oidc_user_role = "dev"
    s.oidc_admin_role = "admin"
    return s


def _cfg(external_url: str = "https://dev.yoops.org") -> Mock:
    c = Mock()
    c.server.external_url = external_url
    return c


def _patches(get_current_user_kw: dict):
    return (
        patch.object(auth_router.rbac_mod, "get_current_user", **get_current_user_kw),
        patch.object(auth_router, "get_settings", _settings),
        patch.object(auth_router, "load_global", lambda: _cfg()),
    )


@pytest.mark.asyncio
async def test_redirects_to_login_when_no_session() -> None:
    p1, p2, p3 = _patches({"return_value": None})
    with p1, p2, p3:
        resp = await auth_router.caddy_verify(Mock())
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://dev.yoops.org/auth/login"


@pytest.mark.asyncio
async def test_redirects_to_login_on_exception() -> None:
    p1, p2, p3 = _patches({"side_effect": RuntimeError("boom")})
    with p1, p2, p3:
        resp = await auth_router.caddy_verify(Mock())
    assert resp.status_code == 302


@pytest.mark.asyncio
async def test_allows_when_role_ok() -> None:
    user = Mock(roles=["admin"], login="admin")
    p1, p2, p3 = _patches({"return_value": user})
    with p1, p2, p3:
        resp = await auth_router.caddy_verify(Mock())
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_forbidden_when_role_mismatch() -> None:
    user = Mock(roles=["someoneelse"], login="x")
    p1, p2, p3 = _patches({"return_value": user})
    with p1, p2, p3:
        resp = await auth_router.caddy_verify(Mock())
    assert resp.status_code == 403
