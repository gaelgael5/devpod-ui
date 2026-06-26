# backend/tests/test_logout.py
"""Logout : doit aussi expirer un cookie de session legacy host-only (posé avant
COOKIE_DOMAIN), que le SessionMiddleware (domain=.yoops.org) ne supprimerait pas."""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from portal.auth.router import logout


@pytest.mark.asyncio
async def test_logout_redirects_and_expires_legacy_cookie() -> None:
    req = Mock()
    req.session = {"user": {"login": "alice"}, "session_id": ""}
    resp = await logout(req)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"
    set_cookies = [v.decode() for k, v in resp.raw_headers if k.lower() == b"set-cookie"]
    # Un Set-Cookie expire portal_session SANS Domain (cible le cookie host-only).
    expired = [c for c in set_cookies if c.startswith("portal_session=")]
    assert expired, "le logout doit émettre un Set-Cookie d'expiration host-only"
    assert all("domain=" not in c.lower() for c in expired)
