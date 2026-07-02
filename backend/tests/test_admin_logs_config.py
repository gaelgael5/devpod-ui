# backend/tests/test_admin_logs_config.py
"""Tests de la config admin des logs centralisés (/admin/logs-config, spec 30 §2)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


def _cfg(
    enabled: bool = True,
    loki_push_url: str | None = "http://192.168.10.196:3100/loki/api/v1/push",
    loki_query_url: str | None = "http://loki:3100",
    grafana_url: str | None = "https://log.dev.yoops.org",
    module: str = "devpod",
    push_token: str | None = None,
):
    from portal.config.models import (
        AuthConfig,
        GlobalConfig,
        LogsConfig,
        OidcConfig,
        ServerConfig,
    )

    return GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(
            oidc=OidcConfig(issuer="", client_id="workspace-portal", client_secret="")
        ),
        logs=LogsConfig(
            enabled=enabled,
            loki_push_url=loki_push_url,
            loki_query_url=loki_query_url,
            grafana_url=grafana_url,
            module=module,
            push_token=push_token,
        ),
    )


def _admin():
    from portal.auth.rbac import UserInfo

    return UserInfo(login="admin", roles=["admin"])


# ── GET ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_returns_current_config() -> None:
    from portal.routes.admin import get_admin_logs_config

    with patch("portal.routes.admin.load_global", return_value=_cfg()):
        res = await get_admin_logs_config(user=_admin())

    assert res == {
        "enabled": True,
        "loki_push_url": "http://192.168.10.196:3100/loki/api/v1/push",
        "loki_query_url": "http://loki:3100",
        "grafana_url": "https://log.dev.yoops.org",
        "module": "devpod",
        "has_push_token": False,
    }


@pytest.mark.asyncio
async def test_get_never_exposes_push_token_value() -> None:
    from portal.routes.admin import get_admin_logs_config

    with patch("portal.routes.admin.load_global", return_value=_cfg(push_token="real-token")):
        res = await get_admin_logs_config(user=_admin())

    assert res["has_push_token"] is True
    assert "push_token" not in res
    assert "real-token" not in str(res)


# ── PUT ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_rejects_enable_without_urls() -> None:
    from fastapi import HTTPException

    from portal.routes.admin import LogsConfigUpdateRequest, put_admin_logs_config

    cfg = _cfg(enabled=False, loki_push_url=None, loki_query_url=None)
    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        pytest.raises(HTTPException) as exc_info,
    ):
        await put_admin_logs_config(
            LogsConfigUpdateRequest(enabled=True), user=_admin(), conn=AsyncMock()
        )

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_put_enables_with_urls() -> None:
    from portal.routes.admin import LogsConfigUpdateRequest, put_admin_logs_config

    cfg = _cfg(enabled=False, loki_push_url=None, loki_query_url=None, grafana_url=None)
    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock) as mock_save,
    ):
        res = await put_admin_logs_config(
            LogsConfigUpdateRequest(
                enabled=True,
                loki_push_url="http://host:3100/loki/api/v1/push",
                loki_query_url="http://loki:3100",
                grafana_url="https://log.dev.yoops.org",
                module="devpod",
            ),
            user=_admin(),
            conn=AsyncMock(),
        )

    assert cfg.logs.enabled is True
    assert cfg.logs.loki_push_url == "http://host:3100/loki/api/v1/push"
    mock_save.assert_awaited_once()
    assert res["enabled"] is True


@pytest.mark.asyncio
async def test_put_disable_does_not_require_urls() -> None:
    from portal.routes.admin import LogsConfigUpdateRequest, put_admin_logs_config

    cfg = _cfg(enabled=True)
    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock),
    ):
        res = await put_admin_logs_config(
            LogsConfigUpdateRequest(enabled=False), user=_admin(), conn=AsyncMock()
        )

    assert cfg.logs.enabled is False
    assert res["enabled"] is False


@pytest.mark.asyncio
async def test_put_preserves_push_token_when_blank() -> None:
    from portal.routes.admin import LogsConfigUpdateRequest, put_admin_logs_config

    cfg = _cfg(push_token="OLD-TOKEN")
    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock),
    ):
        res = await put_admin_logs_config(
            LogsConfigUpdateRequest(
                enabled=True,
                loki_push_url=cfg.logs.loki_push_url,
                loki_query_url=cfg.logs.loki_query_url,
                push_token="",
            ),
            user=_admin(),
            conn=AsyncMock(),
        )

    assert cfg.logs.push_token == "OLD-TOKEN"  # préservé
    assert res["has_push_token"] is True


@pytest.mark.asyncio
async def test_put_replaces_push_token() -> None:
    from portal.routes.admin import LogsConfigUpdateRequest, put_admin_logs_config

    cfg = _cfg(push_token="OLD-TOKEN")
    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock),
    ):
        await put_admin_logs_config(
            LogsConfigUpdateRequest(
                enabled=True,
                loki_push_url=cfg.logs.loki_push_url,
                loki_query_url=cfg.logs.loki_query_url,
                push_token="${vault://logs/loki_push_token}",
            ),
            user=_admin(),
            conn=AsyncMock(),
        )

    assert cfg.logs.push_token == "${vault://logs/loki_push_token}"


@pytest.mark.asyncio
async def test_put_defaults_module_when_blank() -> None:
    from portal.routes.admin import LogsConfigUpdateRequest, put_admin_logs_config

    cfg = _cfg(module="devpod")
    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock),
    ):
        await put_admin_logs_config(
            LogsConfigUpdateRequest(
                enabled=True,
                loki_push_url=cfg.logs.loki_push_url,
                loki_query_url=cfg.logs.loki_query_url,
                module="   ",
            ),
            user=_admin(),
            conn=AsyncMock(),
        )

    assert cfg.logs.module == "devpod"
