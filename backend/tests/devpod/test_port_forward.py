# backend/tests/devpod/test_port_forward.py
"""Cycle de vie des tunnels SSH openvscode (_start_port_forward).

Deux protections indispensables contre les listeners fantômes (le proxy VS Code
se connecte, la connexion est acceptée puis coupée sans réponse → ReadError) :
- ExitOnForwardFailure=yes : un bind raté (port déjà pris) doit faire mourir le
  ssh — le check "tunnel mort qui suit le spawn" le détecte alors et lève ;
- tuer un éventuel tunnel précédent du même workspace avant d'en démarrer un
  nouveau (re-up, reconcile) — sinon l'ancien processus garde le port.
"""
from __future__ import annotations

import asyncio

import pytest


class _FakeProc:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminated = False
        self.stdout = None
        self.stderr = None

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    async def wait(self) -> int:
        return self.returncode or 0


def _bare_service():  # type: ignore[no-untyped-def]
    from portal.devpod.service import DevPodService

    svc = object.__new__(DevPodService)
    svc._devpod_bin = ["devpod"]
    svc._port_forward_procs = {}
    return svc


@pytest.mark.asyncio
async def test_port_forward_cmd_exits_on_forward_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import portal.devpod.service as service_mod

    captured: list[str] = []

    async def _fake_exec(*cmd: str, **kwargs: object) -> _FakeProc:
        captured.extend(cmd)
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(service_mod, "_PORT_FORWARD_SETTLE_S", 0)

    svc = _bare_service()
    await svc._start_port_forward("alice-app", {}, 40000)
    assert "ExitOnForwardFailure=yes" in captured


@pytest.mark.asyncio
async def test_port_forward_replaces_previous_tunnel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import portal.devpod.service as service_mod

    async def _fake_exec(*cmd: str, **kwargs: object) -> _FakeProc:
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(service_mod, "_PORT_FORWARD_SETTLE_S", 0)

    svc = _bare_service()
    old = _FakeProc()
    svc._port_forward_procs["alice-app"] = old

    await svc._start_port_forward("alice-app", {}, 40000)

    assert old.terminated, "l'ancien tunnel doit être terminé avant le nouveau spawn"
    assert svc._port_forward_procs["alice-app"] is not old
