"""Liste des hosts de ressource exposée aux utilisateurs (`/me/resource-hosts`).

En v1, tout host `usage="ressources"` est déployable par n'importe quel user
authentifié. Seuls des champs sûrs sont exposés (jamais les slugs de secrets).
"""

from __future__ import annotations

import pytest

import portal.routes.resource_hosts as rt
from portal.config.models import HostConfig


class _Cfg:
    def __init__(self, hosts: list[HostConfig]) -> None:
        self.hosts = hosts


USER = type("U", (), {"login": "alice"})()


def _hosts() -> list[HostConfig]:
    return [
        HostConfig(name="ws-01", type="ssh", address="10.0.0.1", usage="workspaces"),
        HostConfig(
            name="res-01",
            type="ssh",
            address="10.0.0.200",
            usage="ressources",
            host_cert_slug="host.res-01.cert",
        ),
        HostConfig(name="res-02", type="docker-tls", address="10.0.0.201", usage="ressources"),
        HostConfig(name="portal", type="ssh", address="10.0.0.9", usage="portail"),
    ]


@pytest.mark.asyncio
async def test_lists_only_resource_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rt, "load_global", lambda: _Cfg(_hosts()))
    out = await rt.list_resource_hosts_route(user=USER)
    names = [h["name"] for h in out]
    assert names == ["res-01", "res-02"]


@pytest.mark.asyncio
async def test_exposes_only_safe_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rt, "load_global", lambda: _Cfg(_hosts()))
    out = await rt.list_resource_hosts_route(user=USER)
    first = out[0]
    assert set(first.keys()) == {"name", "address", "type"}
    # Aucun slug de secret ne fuite.
    assert "host_cert_slug" not in first
    assert first["name"] == "res-01" and first["address"] == "10.0.0.200"


@pytest.mark.asyncio
async def test_empty_when_no_resource_host(monkeypatch: pytest.MonkeyPatch) -> None:
    only_ws = [HostConfig(name="ws-01", type="ssh", usage="workspaces")]
    monkeypatch.setattr(rt, "load_global", lambda: _Cfg(only_ws))
    assert await rt.list_resource_hosts_route(user=USER) == []
