"""Route admin des durées de session (idle glissant + plafond absolu)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError


def _cfg():  # type: ignore[no-untyped-def]
    from portal.config.models import AuthConfig, GlobalConfig, OidcConfig, ServerConfig

    return GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
    )


def test_request_rejects_absolute_below_idle() -> None:
    from portal.routes.admin import SessionDurationsRequest

    with pytest.raises(ValidationError):
        SessionDurationsRequest(session_max_age=7200, session_absolute_max_age=3600)


def test_request_rejects_out_of_bounds() -> None:
    from portal.routes.admin import SessionDurationsRequest

    with pytest.raises(ValidationError):
        SessionDurationsRequest(session_max_age=10, session_absolute_max_age=100)  # < 60


def test_request_accepts_valid() -> None:
    from portal.routes.admin import SessionDurationsRequest

    req = SessionDurationsRequest(session_max_age=7200, session_absolute_max_age=43200)
    assert req.session_max_age == 7200
    assert req.session_absolute_max_age == 43200


@pytest.mark.asyncio
async def test_put_persists_and_returns() -> None:
    from portal.auth.rbac import UserInfo
    from portal.routes.admin import SessionDurationsRequest, put_sessions_config

    cfg = _cfg()
    conn = AsyncMock()
    user = UserInfo(login="admin", roles=["admin"])
    body = SessionDurationsRequest(session_max_age=1800, session_absolute_max_age=7200)

    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock) as mock_save,
        patch("portal.routes.admin.set_cached_global") as mock_cache,
    ):
        result = await put_sessions_config(body=body, user=user, conn=conn)

    assert result == {"session_max_age": 1800, "session_absolute_max_age": 7200}
    # Persisté sur le server config.
    assert cfg.server.session_max_age == 1800
    assert cfg.server.session_absolute_max_age == 7200
    mock_save.assert_awaited_once()
    mock_cache.assert_called_once_with(cfg)


@pytest.mark.asyncio
async def test_get_returns_effective_values() -> None:
    from portal.auth.rbac import UserInfo
    from portal.routes.admin import get_sessions_config

    user = UserInfo(login="admin", roles=["admin"])
    # Override admin posé en config → renvoyé tel quel.
    cfg = _cfg()
    cfg.server = cfg.server.model_copy(
        update={"session_max_age": 900, "session_absolute_max_age": 5400}
    )
    with patch("portal.config.store.load_global", return_value=cfg):
        result = await get_sessions_config(user=user)
    assert result == {"session_max_age": 900, "session_absolute_max_age": 5400}
