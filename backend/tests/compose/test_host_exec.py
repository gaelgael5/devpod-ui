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

    # Couture réelle depuis 813f425f : host_exec spawne via spawn_group et nettoie
    # via kill_process_group (kill du GROUPE — un stub sans pid réel ne peut pas
    # subir un vrai killpg, on reproduit son contrat : kill puis moisson).
    async def fake_spawn_group(*args, **kwargs):
        return proc

    async def fake_kill_process_group(p):
        p.kill()
        await p.wait()

    monkeypatch.setattr(host_exec, "spawn_group", fake_spawn_group)
    monkeypatch.setattr(host_exec, "kill_process_group", fake_kill_process_group)


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


# ─── Multiplexage SSH des commandes host (enabler be1112a5) ───────────────────


def test_argv_includes_control_master_options(tmp_path) -> None:
    """Chaque appel host ne doit plus payer un handshake complet : ControlMaster
    mutualise la connexion (l'incident du 24/07 = 10 500 scopes systemd)."""
    argv = host_exec._argv("/tmp/k", "root@10.0.0.1", "true", tmp_path / "kh")
    joined = " ".join(argv)
    assert "ControlMaster=auto" in joined
    assert "ControlPath=" in joined
    assert "ControlPersist=" in joined


def test_control_path_is_stable_per_host_and_distinct_between_hosts(tmp_path) -> None:
    def path_of(address: str) -> str:
        argv = host_exec._argv("/tmp/k", address, "true", tmp_path / "kh")
        return next(a for a in argv if a.startswith("ControlPath="))

    assert path_of("root@10.0.0.1") == path_of("root@10.0.0.1")
    assert path_of("root@10.0.0.1") != path_of("debian@10.0.0.2")
    # Distinct aussi des masters workspaces (répertoire commun) : préfixe dédié.
    assert "host-" in path_of("root@10.0.0.1")


# ─── Sémaphore fail-fast par nœud (enabler be1112a5) ─────────────────────────


@pytest.fixture(autouse=True)
def _clear_semaphores():
    host_exec.clear_host_semaphores()
    yield
    host_exec.clear_host_semaphores()


def _patch_exec_deps(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(host_exec, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(host_exec, "_materialize_system_cert", AsyncMock(return_value="/tmp/k"))


@pytest.mark.asyncio
async def test_run_host_command_fails_fast_when_host_saturated(monkeypatch, tmp_path) -> None:
    """Slots pleins → HostExecError rapide, pas d'empilement de sous-process."""
    _patch_exec_deps(monkeypatch, tmp_path)
    monkeypatch.setattr(host_exec, "HOST_EXEC_ACQUIRE_TIMEOUT_S", 0.05)
    release = asyncio.Event()

    async def slow_capture(argv, **kw):
        await release.wait()
        return (0, "ok", "")

    monkeypatch.setattr(host_exec, "_ssh_capture", slow_capture)
    host = _ssh_host()
    tasks = [
        asyncio.create_task(host_exec.run_host_command(host, "true"))
        for _ in range(host_exec.HOST_EXEC_MAX_CONCURRENT)
    ]
    await asyncio.sleep(0.01)  # laisser les tâches acquérir leurs slots

    with pytest.raises(host_exec.HostExecError, match="satur"):
        await host_exec.run_host_command(host, "true")

    release.set()
    results = await asyncio.gather(*tasks)
    assert all(rc == 0 for rc, _, _ in results)


@pytest.mark.asyncio
async def test_host_saturation_does_not_block_other_hosts(monkeypatch, tmp_path) -> None:
    """La borne est PAR nœud : un host saturé ne bloque pas les autres."""
    _patch_exec_deps(monkeypatch, tmp_path)
    monkeypatch.setattr(host_exec, "HOST_EXEC_ACQUIRE_TIMEOUT_S", 0.05)
    release = asyncio.Event()
    calls: list[str] = []

    async def capture(argv, **kw):
        calls.append(argv[-2])
        if "10.0.0.1" in argv[-2]:
            await release.wait()
        return (0, "ok", "")

    monkeypatch.setattr(host_exec, "_ssh_capture", capture)
    slow = _ssh_host()
    fast = SimpleNamespace(
        name="n3", type="ssh", address="debian@10.0.0.3", host_cert_slug="host.n3.cert"
    )
    tasks = [
        asyncio.create_task(host_exec.run_host_command(slow, "true"))
        for _ in range(host_exec.HOST_EXEC_MAX_CONCURRENT)
    ]
    await asyncio.sleep(0.01)

    rc, out, _err = await host_exec.run_host_command(fast, "true")
    assert (rc, out) == (0, "ok")

    release.set()
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_slots_released_after_completion(monkeypatch, tmp_path) -> None:
    """Les slots se libèrent : N+2 appels séquentiels passent tous."""
    _patch_exec_deps(monkeypatch, tmp_path)

    async def fake_capture(argv, **kw):
        return (0, "ok", "")

    monkeypatch.setattr(host_exec, "_ssh_capture", fake_capture)
    host = _ssh_host()
    for _ in range(host_exec.HOST_EXEC_MAX_CONCURRENT + 2):
        rc, _out, _err = await host_exec.run_host_command(host, "true")
        assert rc == 0
