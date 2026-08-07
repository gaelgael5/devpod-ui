"""Édition des paramètres de connexion d'une machine de test + reveal root PIN.

Tests au niveau route : l'accès DB, le PIN, le secret et l'audit sont substitués
(leur logique est couverte par leurs propres suites). On vérifie ici le contrat
HTTP : validation, garde de propriété, effet sur l'adresse/secret, garde PIN.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import portal.routes.test_vm as test_vm
from portal.auth.rbac import UserInfo, require_user
from portal.config.models import HostConfig
from portal.db.engine import get_conn
from portal.routes.test_vm import router as test_vm_router
from portal.vault.pin import PinLockedError, PinWrongError


class _FakeCtx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_: Any) -> bool:
        return False


class _FakeEngine:
    def connect(self) -> _FakeCtx:
        return _FakeCtx()

    def begin(self) -> _FakeCtx:
        return _FakeCtx()


def _host() -> HostConfig:
    return HostConfig(
        name="host-test-114-1",
        type="ssh",
        address="debian@192.168.10.219",
        vmid="114",
        proxmox_node="pve1",
        usage="tests",
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(test_vm, "_get_engine", lambda: _FakeEngine())
    app = FastAPI()
    app.include_router(test_vm_router, prefix="/me")
    app.dependency_overrides[require_user] = lambda: UserInfo(login="alice", roles=["dev"])
    app.dependency_overrides[get_conn] = lambda: None
    return TestClient(app)


# ─── Édition des paramètres de connexion ─────────────────────────────────────


def _patch_owned(monkeypatch: pytest.MonkeyPatch, *, owned: bool = True) -> None:
    async def _detailed(login: str, ws: str, conn: Any) -> list[tuple[str, str]]:
        return [("host-test-114-1", "test1")]

    async def _is_owned(login: str, ws: str, host: str, conn: Any) -> bool:
        return owned

    monkeypatch.setattr(test_vm, "list_test_hosts_detailed", _detailed)
    monkeypatch.setattr(test_vm, "is_owned_test_host", _is_owned)


def _patch_update_deps(
    monkeypatch: pytest.MonkeyPatch, cfg: SimpleNamespace, stored: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(test_vm, "load_global", lambda: cfg)

    async def _save(_cfg: Any, conn: Any) -> None:
        return None

    async def _store(**kwargs: Any) -> None:
        stored.append(kwargs)

    async def _ssh(login: str, target: str, cmd: str) -> tuple[int, str, str]:
        return (0, "", "")

    monkeypatch.setattr(test_vm, "save_global_db", _save)
    monkeypatch.setattr(test_vm, "store_system_secret", _store)
    monkeypatch.setattr(test_vm, "set_cached_global", lambda _c: None)
    monkeypatch.setattr(test_vm, "run_ssh_capture", _ssh)
    monkeypatch.setattr(test_vm, "build_container_ssh_config_cmd", lambda alias, ip: "noop")


def test_update_connection_ok_updates_address_and_stores_password(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_owned(monkeypatch)
    cfg = SimpleNamespace(hosts=[_host()])
    stored: list[dict[str, Any]] = []
    _patch_update_deps(monkeypatch, cfg, stored)

    resp = client.put(
        "/me/workspaces/devpod/test-vm/host-test-114-1/connection",
        json={"username": "root", "host": "192.168.10.240", "password": "n3w-pass"},
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "alias": "test1",
        "name": "host-test-114-1",
        "ip": "192.168.10.240",
        "user": "root",
        "vmid": "114",
    }
    # L'adresse du host est réécrite en <user>@<host>.
    assert cfg.hosts[0].address == "root@192.168.10.240"
    # Le mot de passe fourni est (re)stocké sous le slug root-password.
    assert len(stored) == 1
    assert stored[0]["slug"] == "host.host-test-114-1.root-password"
    assert stored[0]["value"] == "n3w-pass"


def test_update_connection_without_password_leaves_secret_untouched(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_owned(monkeypatch)
    cfg = SimpleNamespace(hosts=[_host()])
    stored: list[dict[str, Any]] = []
    _patch_update_deps(monkeypatch, cfg, stored)

    resp = client.put(
        "/me/workspaces/devpod/test-vm/host-test-114-1/connection",
        json={"username": "debian", "host": "host-test-114-1.home.lan"},
    )
    assert resp.status_code == 200
    assert cfg.hosts[0].address == "debian@host-test-114-1.home.lan"
    assert stored == []


def test_update_connection_shared_vm_is_403(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_owned(monkeypatch, owned=False)
    _patch_update_deps(monkeypatch, SimpleNamespace(hosts=[_host()]), [])
    resp = client.put(
        "/me/workspaces/devpod/test-vm/host-test-114-1/connection",
        json={"username": "root", "host": "10.0.0.5"},
    )
    assert resp.status_code == 403


def test_update_connection_rejects_bad_username(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_owned(monkeypatch)
    _patch_update_deps(monkeypatch, SimpleNamespace(hosts=[_host()]), [])
    resp = client.put(
        "/me/workspaces/devpod/test-vm/host-test-114-1/connection",
        json={"username": "ro ot", "host": "10.0.0.5"},
    )
    assert resp.status_code == 422


def test_update_connection_rejects_bad_host(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_owned(monkeypatch)
    _patch_update_deps(monkeypatch, SimpleNamespace(hosts=[_host()]), [])
    resp = client.put(
        "/me/workspaces/devpod/test-vm/host-test-114-1/connection",
        json={"username": "root", "host": "10.0.0.5; rm -rf /"},
    )
    assert resp.status_code == 422


def test_update_connection_unknown_host_is_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _detailed(login: str, ws: str, conn: Any) -> list[tuple[str, str]]:
        return []

    async def _is_owned(login: str, ws: str, host: str, conn: Any) -> bool:
        return False

    monkeypatch.setattr(test_vm, "list_test_hosts_detailed", _detailed)
    monkeypatch.setattr(test_vm, "is_owned_test_host", _is_owned)
    resp = client.put(
        "/me/workspaces/devpod/test-vm/host-test-114-1/connection",
        json={"username": "root", "host": "10.0.0.5"},
    )
    assert resp.status_code == 404


# ─── Reveal du mot de passe root (PIN) ───────────────────────────────────────


def _patch_reveal_common(monkeypatch: pytest.MonkeyPatch, *, owned: bool = True) -> None:
    async def _is_owned(login: str, ws: str, host: str, conn: Any) -> bool:
        return owned

    async def _denied(login: str, host: str, error: str) -> None:
        return None

    async def _audit(conn: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(test_vm, "is_owned_test_host", _is_owned)
    monkeypatch.setattr(test_vm, "_sid", lambda request: "sid-test")
    monkeypatch.setattr(test_vm, "_audit_root_pw_denied", _denied)
    monkeypatch.setattr(test_vm, "_audit_record", _audit)


def test_reveal_ok_returns_value(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_reveal_common(monkeypatch)

    async def _unlock(login: str, pin: str, sid: str, conn: Any) -> None:
        return None

    async def _reveal(slug: str, conn: Any) -> str:
        assert slug == "host.host-test-114-1.root-password"
        return "r00t-pass"

    monkeypatch.setattr(test_vm, "unlock_pin", _unlock)
    monkeypatch.setattr(test_vm, "reveal_system_secret", _reveal)
    resp = client.post(
        "/me/workspaces/devpod/test-vm/host-test-114-1/root-password/reveal",
        json={"pin": "123456"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"value": "r00t-pass"}


def test_reveal_wrong_pin_is_403_and_secret_never_read(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_reveal_common(monkeypatch)
    revealed = False

    async def _unlock(login: str, pin: str, sid: str, conn: Any) -> None:
        raise PinWrongError("Incorrect PIN")

    async def _reveal(slug: str, conn: Any) -> str:
        nonlocal revealed
        revealed = True
        return "x"

    monkeypatch.setattr(test_vm, "unlock_pin", _unlock)
    monkeypatch.setattr(test_vm, "reveal_system_secret", _reveal)
    resp = client.post(
        "/me/workspaces/devpod/test-vm/host-test-114-1/root-password/reveal",
        json={"pin": "000000"},
    )
    assert resp.status_code == 403
    assert revealed is False


def test_reveal_locked_pin_is_423(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_reveal_common(monkeypatch)

    async def _unlock(login: str, pin: str, sid: str, conn: Any) -> None:
        raise PinLockedError(30.0)

    monkeypatch.setattr(test_vm, "unlock_pin", _unlock)
    resp = client.post(
        "/me/workspaces/devpod/test-vm/host-test-114-1/root-password/reveal",
        json={"pin": "123456"},
    )
    assert resp.status_code == 423


def test_reveal_not_owned_is_404_without_consuming_pin(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_reveal_common(monkeypatch, owned=False)
    called = False

    async def _unlock(login: str, pin: str, sid: str, conn: Any) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(test_vm, "unlock_pin", _unlock)
    resp = client.post(
        "/me/workspaces/devpod/test-vm/host-test-114-1/root-password/reveal",
        json={"pin": "123456"},
    )
    assert resp.status_code == 404
    assert called is False


def test_reveal_missing_secret_is_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_reveal_common(monkeypatch)

    async def _unlock(login: str, pin: str, sid: str, conn: Any) -> None:
        return None

    async def _reveal(slug: str, conn: Any) -> str:
        raise KeyError(slug)

    monkeypatch.setattr(test_vm, "unlock_pin", _unlock)
    monkeypatch.setattr(test_vm, "reveal_system_secret", _reveal)
    resp = client.post(
        "/me/workspaces/devpod/test-vm/host-test-114-1/root-password/reveal",
        json={"pin": "123456"},
    )
    assert resp.status_code == 404


def test_reveal_malformed_pin_is_422(client: TestClient) -> None:
    resp = client.post(
        "/me/workspaces/devpod/test-vm/host-test-114-1/root-password/reveal",
        json={"pin": "12ab"},
    )
    assert resp.status_code == 422
