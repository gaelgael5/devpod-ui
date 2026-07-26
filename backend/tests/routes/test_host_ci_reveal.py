"""Reveal du mot de passe console d'un host derrière PIN (enabler 6e3d5f3a).

Le secret n'est déchiffré et renvoyé qu'après validation du PIN vault ; toute
tentative (succès ou refus) est tracée. Tests au niveau route : les dépendances
PIN/secret/audit sont substituées — leur crypto est couverte par leurs propres
suites.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import portal.routes.host_secrets as host_secrets
from portal.auth.rbac import UserInfo, require_admin
from portal.db.engine import get_conn
from portal.routes.host_secrets import router as host_secrets_router
from portal.vault.pin import PinLockedError, PinNotSetupError, PinWrongError

_HOST = SimpleNamespace(name="pve1", ci_password_secret_slug="host.pve1.ci-password")
_HOST_SANS_SECRET = SimpleNamespace(name="pve2", ci_password_secret_slug="")


@pytest.fixture
def audit_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def _record(conn: Any, **kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(host_secrets, "_audit_record", _record)
    return calls


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        host_secrets,
        "load_global",
        lambda: SimpleNamespace(hosts=[_HOST, _HOST_SANS_SECRET]),
    )
    monkeypatch.setattr(host_secrets, "_sid", lambda request: "sid-test")

    app = FastAPI()
    app.include_router(host_secrets_router, prefix="/admin")
    app.dependency_overrides[require_admin] = lambda: UserInfo(
        login="bob", roles=["admin"]
    )
    app.dependency_overrides[get_conn] = lambda: None
    return TestClient(app)


def _patch_pin_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _unlock(login: str, pin: str, sid: str, conn: Any) -> None:
        return None

    monkeypatch.setattr(host_secrets, "unlock_pin", _unlock)


def _patch_reveal(monkeypatch: pytest.MonkeyPatch, value: str = "s3cret") -> None:
    async def _reveal(slug: str, conn: Any) -> str:
        assert slug == _HOST.ci_password_secret_slug
        return value

    monkeypatch.setattr(host_secrets, "reveal_system_secret", _reveal)


def test_reveal_ok_returns_value_and_audits(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    audit_calls: list[dict[str, Any]],
) -> None:
    _patch_pin_ok(monkeypatch)
    _patch_reveal(monkeypatch)
    resp = client.post(
        "/admin/hosts/pve1/ci-password/reveal", json={"pin": "123456"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"value": "s3cret"}
    assert len(audit_calls) == 1
    assert audit_calls[0]["status"] == "ok"
    assert audit_calls[0]["owner_login"] == "bob"
    assert audit_calls[0]["backend_id"] == "pve1"


def test_wrong_pin_is_403_and_secret_never_read(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    audit_calls: list[dict[str, Any]],
) -> None:
    async def _unlock(login: str, pin: str, sid: str, conn: Any) -> None:
        raise PinWrongError("Incorrect PIN")

    revealed = False

    async def _reveal(slug: str, conn: Any) -> str:
        nonlocal revealed
        revealed = True
        return "s3cret"

    monkeypatch.setattr(host_secrets, "unlock_pin", _unlock)
    monkeypatch.setattr(host_secrets, "reveal_system_secret", _reveal)
    resp = client.post(
        "/admin/hosts/pve1/ci-password/reveal", json={"pin": "000000"}
    )
    assert resp.status_code == 403
    assert revealed is False
    assert len(audit_calls) == 1
    assert audit_calls[0]["status"] == "denied"


def test_locked_pin_is_423(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    audit_calls: list[dict[str, Any]],
) -> None:
    async def _unlock(login: str, pin: str, sid: str, conn: Any) -> None:
        raise PinLockedError(42.0)

    monkeypatch.setattr(host_secrets, "unlock_pin", _unlock)
    resp = client.post(
        "/admin/hosts/pve1/ci-password/reveal", json={"pin": "123456"}
    )
    assert resp.status_code == 423
    assert audit_calls[0]["status"] == "denied"


def test_pin_not_setup_is_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _unlock(login: str, pin: str, sid: str, conn: Any) -> None:
        raise PinNotSetupError("No PIN for 'bob'")

    monkeypatch.setattr(host_secrets, "unlock_pin", _unlock)
    resp = client.post(
        "/admin/hosts/pve1/ci-password/reveal", json={"pin": "123456"}
    )
    assert resp.status_code == 404


def test_unknown_host_is_404_without_consuming_pin_attempt(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = False

    async def _unlock(login: str, pin: str, sid: str, conn: Any) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(host_secrets, "unlock_pin", _unlock)
    resp = client.post(
        "/admin/hosts/nope/ci-password/reveal", json={"pin": "123456"}
    )
    assert resp.status_code == 404
    assert called is False


def test_host_without_secret_is_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_pin_ok(monkeypatch)
    resp = client.post(
        "/admin/hosts/pve2/ci-password/reveal", json={"pin": "123456"}
    )
    assert resp.status_code == 404


def test_missing_secret_row_is_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_pin_ok(monkeypatch)

    async def _reveal(slug: str, conn: Any) -> str:
        raise KeyError(slug)

    monkeypatch.setattr(host_secrets, "reveal_system_secret", _reveal)
    resp = client.post(
        "/admin/hosts/pve1/ci-password/reveal", json={"pin": "123456"}
    )
    assert resp.status_code == 404


def test_malformed_pin_is_422(client: TestClient) -> None:
    resp = client.post(
        "/admin/hosts/pve1/ci-password/reveal", json={"pin": "12ab"}
    )
    assert resp.status_code == 422
