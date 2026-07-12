import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from portal.devpod import host_exec


def _ssh_host():
    return SimpleNamespace(
        name="n1",
        type="ssh",
        address="root@10.0.0.1",
        host_cert_slug="host.n1.cert",
    )


def _tls_host():
    return SimpleNamespace(name="n2", type="docker-tls", address="", host_cert_slug="")


def test_require_ssh_host_rejects_non_ssh() -> None:
    with pytest.raises(host_exec.HostExecError):
        host_exec._require_ssh_host(_tls_host())


@pytest.mark.asyncio
async def test_run_host_command_invokes_ssh(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(host_exec, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(host_exec, "_materialize_system_cert", AsyncMock(return_value="/tmp/k"))
    captured = {}

    async def fake_capture(argv, **kw):
        captured["argv"] = argv
        return (0, "ok", "")

    monkeypatch.setattr(host_exec, "_ssh_capture", fake_capture)
    rc, out, err = await host_exec.run_host_command(_ssh_host(), "docker compose ps")
    assert (rc, out) == (0, "ok")
    assert "root@10.0.0.1" in captured["argv"] and "docker compose ps" in captured["argv"]


@pytest.mark.asyncio
async def test_write_host_file_rejects_non_ssh() -> None:
    with pytest.raises(host_exec.HostExecError):
        await host_exec.write_host_file(_tls_host(), "/x", "y")


@pytest.mark.asyncio
async def test_write_host_file_rejects_nul_path() -> None:
    with pytest.raises(host_exec.HostExecError):
        await host_exec.write_host_file(_ssh_host(), "/etc/foo\x00bar", "y")


@pytest.mark.asyncio
async def test_write_host_file_base64_roundtrip(monkeypatch) -> None:
    monkeypatch.setattr(host_exec, "_materialize_system_cert", AsyncMock(return_value="/tmp/k"))
    seen = {}

    async def fake_run(host, command, *, timeout=120.0):
        seen["cmd"] = command
        return (0, "", "")

    monkeypatch.setattr(host_exec, "run_host_command", fake_run)
    await host_exec.write_host_file(_ssh_host(), "devpod-compose/d1/.env", "A=1\n")
    assert "base64 -d" in seen["cmd"] and "mkdir -p" in seen["cmd"]
    assert base64.b64encode(b"A=1\n").decode() in seen["cmd"]
    assert "devpod-compose/d1/.env" in seen["cmd"]


@pytest.mark.asyncio
async def test_write_host_file_rejects_tilde_path() -> None:
    with pytest.raises(host_exec.HostExecError):
        await host_exec.write_host_file(_ssh_host(), "~/devpod-compose/d1/.env", "A=1\n")


class _FakeStreamProc:
    """Simule un asyncio.subprocess.Process pour stream_host_command."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)
        self.returncode: int | None = None
        self.killed = False
        self.waited = False
        self.stdout = self

    async def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        # Plus de ligne disponible : bloque indéfiniment (simule un process qui
        # tourne encore), comme le ferait un vrai stdout ouvert sans EOF.
        await asyncio.Event().wait()
        return b""  # pragma: no cover — jamais atteint

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        self.waited = True
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def _patch_stream_deps(monkeypatch, tmp_path, proc: _FakeStreamProc) -> None:
    monkeypatch.setattr(host_exec, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(host_exec, "_materialize_system_cert", AsyncMock(return_value="/tmp/k"))

    async def fake_create_subprocess_exec(*args, **kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)


@pytest.mark.asyncio
async def test_stream_host_command_yields_lines_and_reaps_process(monkeypatch, tmp_path) -> None:
    proc = _FakeStreamProc([b"hello\n", b"world\n", b""])
    _patch_stream_deps(monkeypatch, tmp_path, proc)

    lines = [line async for line in host_exec.stream_host_command(_ssh_host(), "cmd")]

    assert lines == ["hello", "world"]
    assert proc.waited is True
    assert proc.killed is False


@pytest.mark.asyncio
async def test_stream_host_command_kills_process_on_early_disconnect(monkeypatch, tmp_path) -> None:
    """Bug 016 : si le consommateur ferme le générateur en cours de stream (client
    HTTP déconnecté), asyncio lève GeneratorExit — le sous-process ssh doit être
    tué et attendu, pas laissé orphelin."""
    proc = _FakeStreamProc([b"line1\n"])
    _patch_stream_deps(monkeypatch, tmp_path, proc)

    gen = host_exec.stream_host_command(_ssh_host(), "cmd")
    first = await gen.__anext__()
    assert first == "line1"

    await gen.aclose()

    assert proc.killed is True
    assert proc.waited is True
