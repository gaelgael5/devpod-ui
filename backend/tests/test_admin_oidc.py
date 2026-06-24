# backend/tests/test_admin_oidc.py
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _cfg(client_secret: str = "sek"):
    from portal.config.models import AuthConfig, GlobalConfig, OidcConfig, ServerConfig

    return GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(
            oidc=OidcConfig(
                issuer="https://iss", client_id="cid", client_secret=client_secret
            )
        ),
    )


def _admin():
    from portal.auth.rbac import UserInfo

    return UserInfo(login="admin", roles=["admin"])


def _fake_engine():
    eng = MagicMock()

    @asynccontextmanager
    async def _begin():
        yield AsyncMock()

    eng.begin = lambda: _begin()
    return eng


# ── GET ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_oidc_hides_secret() -> None:
    from portal.routes.admin import get_admin_oidc

    with patch("portal.routes.admin.load_global", return_value=_cfg("sek")):
        res = await get_admin_oidc(user=_admin())
    assert res == {"issuer": "https://iss", "client_id": "cid", "has_secret": True}
    assert "client_secret" not in res


@pytest.mark.asyncio
async def test_get_oidc_has_secret_false_when_empty() -> None:
    from portal.routes.admin import get_admin_oidc

    with patch("portal.routes.admin.load_global", return_value=_cfg("")):
        res = await get_admin_oidc(user=_admin())
    assert res["has_secret"] is False


# ── PUT ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_oidc_preserves_secret_when_empty() -> None:
    from portal.routes.admin import OidcUpdateRequest, put_admin_oidc

    cfg = _cfg("OLD")
    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.db.engine._get_engine", return_value=_fake_engine()),
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock),
    ):
        res = await put_admin_oidc(
            OidcUpdateRequest(issuer="https://new", client_id="ncid", client_secret=""),
            user=_admin(),
        )
    assert res["issuer"] == "https://new"
    assert res["client_id"] == "ncid"
    assert cfg.auth.oidc.client_secret == "OLD"  # préservé


@pytest.mark.asyncio
async def test_put_oidc_replaces_secret() -> None:
    from portal.routes.admin import OidcUpdateRequest, put_admin_oidc

    cfg = _cfg("OLD")
    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.db.engine._get_engine", return_value=_fake_engine()),
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock),
    ):
        await put_admin_oidc(
            OidcUpdateRequest(issuer="https://i", client_id="c", client_secret="NEW"),
            user=_admin(),
        )
    assert cfg.auth.oidc.client_secret == "NEW"  # remplacé
