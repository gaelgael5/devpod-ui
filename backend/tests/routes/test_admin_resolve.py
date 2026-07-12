from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from portal.auth.rbac import UserInfo
from portal.routes.admin import ResolveHostRequest, resolve_workspace_host

_ADMIN = UserInfo(login="admin", roles=["admin"])


@pytest.mark.asyncio
async def test_resolve_ip_literal_returned_as_is() -> None:
    """Une IP littérale n'est pas résolue : renvoyée telle quelle."""
    out = await resolve_workspace_host(ResolveHostRequest(host="192.168.10.50"), user=_ADMIN)
    assert out == {"fqdn": "192.168.10.50", "ip": "192.168.10.50"}


@pytest.mark.asyncio
async def test_resolve_empty_host_422() -> None:
    """Un host vide → 422."""
    with pytest.raises(HTTPException) as exc:
        await resolve_workspace_host(ResolveHostRequest(host="  "), user=_ADMIN)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_resolve_hostname_uses_local_domain(monkeypatch) -> None:
    """Un hostname est résolu via `<host>.<local_domain>`."""
    import portal.routes.admin as admin_mod

    monkeypatch.setattr(
        admin_mod,
        "load_global",
        lambda: SimpleNamespace(server=SimpleNamespace(local_domain="home.lan")),
    )
    monkeypatch.setattr(admin_mod, "resolve_ipv4", AsyncMock(return_value="192.168.10.42"))

    out = await resolve_workspace_host(ResolveHostRequest(host="portal"), user=_ADMIN)
    assert out == {"fqdn": "portal.home.lan", "ip": "192.168.10.42"}


@pytest.mark.asyncio
async def test_resolve_failure_502(monkeypatch) -> None:
    """Échec de résolution → 502."""
    import portal.routes.admin as admin_mod

    monkeypatch.setattr(
        admin_mod,
        "load_global",
        lambda: SimpleNamespace(server=SimpleNamespace(local_domain="home.lan")),
    )
    monkeypatch.setattr(admin_mod, "resolve_ipv4", AsyncMock(side_effect=OSError("no address")))

    with pytest.raises(HTTPException) as exc:
        await resolve_workspace_host(ResolveHostRequest(host="portal"), user=_ADMIN)
    assert exc.value.status_code == 502
