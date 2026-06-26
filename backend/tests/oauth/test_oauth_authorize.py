# backend/tests/oauth/test_oauth_authorize.py
"""/oauth/authorize + /oauth/authorize/decision (handlers, dépendances mockées)."""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from portal.routes import oauth as r


def _cfg() -> Mock:
    c = Mock()
    c.server.external_url = "https://dev.yoops.org"
    return c


@pytest.mark.asyncio
async def test_authorize_no_session_redirects_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r, "_validate_client", AsyncMock())
    monkeypatch.setattr(r, "get_current_user", lambda req: None)
    monkeypatch.setattr(r, "load_global", _cfg)
    res = await r.authorize(
        request=Mock(), client_id="c1", redirect_uri="https://claude.ai/cb",
        code_challenge="ch", conn=None,
    )
    assert res.status_code == 302
    assert "/auth/login" in res.headers["location"]


@pytest.mark.asyncio
async def test_authorize_session_redirects_consent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r, "_validate_client", AsyncMock())
    monkeypatch.setattr(r, "get_current_user", lambda req: Mock(login="alice"))
    monkeypatch.setattr(r, "load_global", _cfg)
    res = await r.authorize(
        request=Mock(), client_id="c1", redirect_uri="https://claude.ai/cb",
        code_challenge="ch", conn=None,
    )
    assert res.status_code == 302
    assert "/oauth/consent" in res.headers["location"]


@pytest.mark.asyncio
async def test_decision_approve_emits_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r, "get_current_user", lambda req: Mock(login="alice"))
    monkeypatch.setattr(r, "_validate_client", AsyncMock())
    monkeypatch.setattr(r.service, "make_authcode", AsyncMock(return_value="mcpac_code"))
    body = r.DecisionBody(
        client_id="c1", redirect_uri="https://claude.ai/cb", code_challenge="ch",
        state="s1", approve=True, grants=[],
    )
    res = await r.decision(body, request=Mock(), conn=None)
    assert "code=mcpac_code" in res["redirect"]
    assert "state=s1" in res["redirect"]


@pytest.mark.asyncio
async def test_decision_deny_redirects_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r, "get_current_user", lambda req: Mock(login="alice"))
    monkeypatch.setattr(r, "_validate_client", AsyncMock())
    body = r.DecisionBody(
        client_id="c1", redirect_uri="https://claude.ai/cb", code_challenge="ch", approve=False,
    )
    res = await r.decision(body, request=Mock(), conn=None)
    assert "error=access_denied" in res["redirect"]
