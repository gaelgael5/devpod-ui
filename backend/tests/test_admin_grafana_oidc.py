# backend/tests/test_admin_grafana_oidc.py
"""Tests de la config SSO Grafana (/admin/grafana-oidc) — distincte de /oidc."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


def _cfg(
    oauth_secret: str = "gf-sek",
    issuer: str = "https://security.yoops.org/realms/yoops",
    grafana_url: str | None = "http://192.168.10.196:3001",
):
    from portal.config.models import AuthConfig, GlobalConfig, LogsConfig, OidcConfig, ServerConfig

    return GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(
            oidc=OidcConfig(issuer=issuer, client_id="workspace-portal", client_secret="x")
        ),
        logs=LogsConfig(
            enabled=True, grafana_url=grafana_url, grafana_oauth_client_secret=oauth_secret
        ),
    )


def _admin():
    from portal.auth.rbac import UserInfo

    return UserInfo(login="admin", roles=["admin"])


# ── GET ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_derives_keycloak_endpoints_from_issuer() -> None:
    from portal.routes.admin import get_admin_grafana_oidc

    with patch("portal.routes.admin.load_global", return_value=_cfg()):
        res = await get_admin_grafana_oidc(user=_admin())

    assert res["auth_url"] == "https://security.yoops.org/realms/yoops/protocol/openid-connect/auth"
    assert res["token_url"] == "https://security.yoops.org/realms/yoops/protocol/openid-connect/token"
    assert res["userinfo_url"] == (
        "https://security.yoops.org/realms/yoops/protocol/openid-connect/userinfo"
    )
    assert res["client_id"] == "agflow-grafana"


@pytest.mark.asyncio
async def test_get_never_exposes_secret_value() -> None:
    from portal.routes.admin import get_admin_grafana_oidc

    with patch("portal.routes.admin.load_global", return_value=_cfg("real-secret")):
        res = await get_admin_grafana_oidc(user=_admin())

    assert res["has_secret"] is True
    assert "client_secret" not in res
    assert "real-secret" not in str(res)


@pytest.mark.asyncio
async def test_get_has_secret_false_when_unset() -> None:
    from portal.routes.admin import get_admin_grafana_oidc

    with patch("portal.routes.admin.load_global", return_value=_cfg(oauth_secret="")):
        res = await get_admin_grafana_oidc(user=_admin())

    assert res["has_secret"] is False


@pytest.mark.asyncio
async def test_get_redirect_uri_derived_from_grafana_url() -> None:
    from portal.routes.admin import get_admin_grafana_oidc

    with patch(
        "portal.routes.admin.load_global",
        return_value=_cfg(grafana_url="http://192.168.10.196:3001/"),
    ):
        res = await get_admin_grafana_oidc(user=_admin())

    assert res["redirect_uri"] == "http://192.168.10.196:3001/login/generic_oauth"


@pytest.mark.asyncio
async def test_get_redirect_uri_none_when_grafana_url_unset() -> None:
    from portal.routes.admin import get_admin_grafana_oidc

    with patch("portal.routes.admin.load_global", return_value=_cfg(grafana_url=None)):
        res = await get_admin_grafana_oidc(user=_admin())

    assert res["redirect_uri"] is None


# ── PUT ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_preserves_secret_when_blank(tmp_path) -> None:
    from portal.routes.admin import GrafanaOidcUpdateRequest, put_admin_grafana_oidc

    cfg = _cfg("OLD-SECRET")
    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock),
        patch("portal.routes.admin._data_root", return_value=tmp_path),
        patch("portal.routes.admin.update_env_file") as mock_env,
    ):
        res = await put_admin_grafana_oidc(
            GrafanaOidcUpdateRequest(client_id="agflow-grafana", client_secret=""),
            user=_admin(),
            conn=AsyncMock(),
        )

    assert cfg.logs.grafana_oauth_client_secret == "OLD-SECRET"  # préservé
    assert res["has_secret"] is True
    # client_id/URLs toujours réécrits (idempotent), mais pas le secret vide.
    mock_env.assert_called_once()
    _, written_kv = mock_env.call_args[0]
    assert written_kv["GF_OAUTH_CLIENT_ID"] == "agflow-grafana"
    assert "GF_OAUTH_CLIENT_SECRET" not in written_kv


@pytest.mark.asyncio
async def test_put_replaces_secret_and_writes_env_file(tmp_path) -> None:
    from portal.routes.admin import GrafanaOidcUpdateRequest, put_admin_grafana_oidc

    cfg = _cfg("OLD-SECRET")
    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock),
        patch("portal.routes.admin._data_root", return_value=tmp_path),
        patch("portal.routes.admin.update_env_file") as mock_env,
    ):
        await put_admin_grafana_oidc(
            GrafanaOidcUpdateRequest(client_id="my-grafana", client_secret="NEW-SECRET"),
            user=_admin(),
            conn=AsyncMock(),
        )

    assert cfg.logs.grafana_oauth_client_id == "my-grafana"
    assert cfg.logs.grafana_oauth_client_secret == "NEW-SECRET"
    mock_env.assert_called_once()
    written_path, written_kv = mock_env.call_args[0]
    assert written_path == tmp_path / ".env"
    assert written_kv["GF_OAUTH_CLIENT_ID"] == "my-grafana"
    assert written_kv["GF_OAUTH_CLIENT_SECRET"] == "NEW-SECRET"
    assert written_kv["GF_OAUTH_AUTH_URL"].endswith("/protocol/openid-connect/auth")
    assert written_kv["GF_OAUTH_TOKEN_URL"].endswith("/protocol/openid-connect/token")
    assert written_kv["GF_OAUTH_API_URL"].endswith("/protocol/openid-connect/userinfo")


@pytest.mark.asyncio
async def test_put_rejects_when_portal_oidc_issuer_unset() -> None:
    from fastapi import HTTPException

    from portal.routes.admin import GrafanaOidcUpdateRequest, put_admin_grafana_oidc

    cfg = _cfg(issuer="")
    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        pytest.raises(HTTPException) as exc_info,
    ):
        await put_admin_grafana_oidc(
            GrafanaOidcUpdateRequest(client_secret="NEW"), user=_admin(), conn=AsyncMock()
        )

    assert exc_info.value.status_code == 422
