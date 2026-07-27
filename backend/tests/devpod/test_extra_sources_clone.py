from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path

import pytest

from portal.config.models import GitCredential, SourceSpec
from portal.devpod.service import DevPodService, _deferred_clone_command

# --- _deferred_clone_command : construction de la commande de clone post-readiness ---


def test_deferred_clone_command_uses_basic_auth_header() -> None:
    cmd = _deferred_clone_command("https://gitlab.example.com/team/repo.git", "", "alice", "s3cr3t")
    expected = base64.b64encode(b"alice:s3cr3t").decode()
    assert f'http.extraHeader="Authorization: Basic {expected}"' in cmd
    # Le token n'apparaît jamais en clair (ni dans l'URL, ni ailleurs).
    assert "s3cr3t" not in cmd


def test_deferred_clone_command_disables_devpod_credential_path() -> None:
    cmd = _deferred_clone_command("https://gitlab.example.com/t/r.git", "", "u", "t")
    assert "GIT_ASKPASS=/bin/false" in cmd
    assert "GIT_TERMINAL_PROMPT=0" in cmd
    assert "credential.helper=" in cmd


def test_deferred_clone_command_is_idempotent() -> None:
    cmd = _deferred_clone_command("https://gitlab.example.com/t/repo.git", "", "u", "t")
    # Skip si le répertoire cible existe déjà (re-up de réconciliation).
    assert "if [ -e /workspaces/repo ]; then exit 0; fi;" in cmd
    assert "clone " in cmd
    assert cmd.rstrip().endswith("/workspaces/repo")


def test_deferred_clone_command_with_branch() -> None:
    cmd = _deferred_clone_command("https://gitlab.example.com/t/r.git", "dev/x", "u", "t")
    assert "-b dev/x " in cmd


def test_deferred_clone_command_canonicalizes_gitlab_url() -> None:
    # GitLab self-hosted : le suffixe .git est ajouté (évite le 301 sur le chemin nu).
    cmd = _deferred_clone_command("https://gitlab.example.com/team/repo", "", "u", "t")
    assert "https://gitlab.example.com/team/repo.git" in cmd


def test_deferred_clone_command_rejects_dash_url() -> None:
    with pytest.raises(ValueError, match="must not start with"):
        _deferred_clone_command("--upload-pack=evil", "", "u", "t")


def test_deferred_clone_command_rejects_dash_branch() -> None:
    with pytest.raises(ValueError, match="must not start with"):
        _deferred_clone_command("https://gitlab.example.com/t/r.git", "-x", "u", "t")


# --- _deferred_ssh_clone_command : clone post-readiness via clé SSH ---


def test_ssh_clone_command_converts_https_to_git_at() -> None:
    from portal.devpod.service import _deferred_ssh_clone_command

    cmd = _deferred_ssh_clone_command("https://gitlab.example.com/team/repo.git", "", "KEY")
    assert "git@gitlab.example.com:team/repo.git" in cmd
    assert "GIT_SSH_COMMAND=" in cmd
    assert "/workspaces/repo" in cmd


def test_ssh_clone_command_keeps_git_at_url() -> None:
    from portal.devpod.service import _deferred_ssh_clone_command

    cmd = _deferred_ssh_clone_command("git@github.com:o/p.git", "dev", "KEY")
    assert "git@github.com:o/p.git" in cmd
    assert "-b dev " in cmd


def test_ssh_clone_command_materializes_key_in_tempfile() -> None:
    from portal.devpod.service import _deferred_ssh_clone_command

    cmd = _deferred_ssh_clone_command("git@h:o/p.git", "", "PRIVATE-KEY-BODY")
    # Clé écrite dans un mktemp 0600, effacée par trap — jamais en dur sur disque.
    assert "mktemp" in cmd
    assert "chmod 600" in cmd
    assert "trap 'rm -f" in cmd
    assert "PRIVATE-KEY-BODY" in cmd  # transmise via la commande (conteneur mono-locataire)


def test_ssh_clone_command_is_idempotent() -> None:
    from portal.devpod.service import _deferred_ssh_clone_command

    cmd = _deferred_ssh_clone_command("git@h:o/repo.git", "", "K")
    assert "if [ -e /workspaces/repo ]; then exit 0; fi;" in cmd


def test_ssh_clone_command_rejects_dash_url() -> None:
    from portal.devpod.service import _deferred_ssh_clone_command

    with pytest.raises(ValueError, match="must not start with"):
        _deferred_ssh_clone_command("-oProxyCommand=evil", "", "K")


# --- _split_extra_sources : répartition inline vs post-readiness ---


class _FakeUserCfg:
    def __init__(self, creds: list[GitCredential]) -> None:
        self.git_credentials = creds


@pytest.mark.asyncio
async def test_split_defers_authenticated_sources(monkeypatch, global_cfg, fake_devpod_bin) -> None:
    creds = [
        GitCredential(name="gl", host="gitlab.example.com", kind="token", token="t", username="u"),
        GitCredential(name="deploy", host="github.com", kind="ssh", key_path="/k"),
        GitCredential(name="broken", host="x", kind="ssh", key_path=""),  # ssh sans clé → inline
    ]

    async def _fake_load_user(login: str):
        return _FakeUserCfg(creds)

    monkeypatch.setattr("portal.devpod.service.load_user", _fake_load_user)
    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)

    sources = [
        SourceSpec(url="https://gitlab.example.com/t/r.git", git_credential="gl"),  # token→deferred
        SourceSpec(url="git@github.com:o/p.git", git_credential="deploy"),  # ssh → deferred
        SourceSpec(url="https://x/t/r.git", git_credential="broken"),  # ssh sans clé → inline
        SourceSpec(url="https://github.com/pub/lib.git"),  # public → inline
    ]
    inline, deferred = await svc._split_extra_sources("alice", sources)

    assert {d[0].url for d in deferred} == {
        "https://gitlab.example.com/t/r.git",
        "git@github.com:o/p.git",
    }
    assert {s.url for s in inline} == {
        "https://x/t/r.git",
        "https://github.com/pub/lib.git",
    }


@pytest.mark.asyncio
async def test_split_empty_returns_empty(global_cfg, fake_devpod_bin) -> None:
    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    inline, deferred = await svc._split_extra_sources("alice", [])
    assert inline == []
    assert deferred == []


# --- _clone_deferred_sources : orchestration ws_exec (best-effort, pas de fuite) ---


@pytest.mark.asyncio
async def test_clone_deferred_invokes_ws_exec_per_source(
    monkeypatch, global_cfg, fake_devpod_bin
) -> None:
    calls: list[tuple[str, str]] = []

    async def _fake_ws_exec(login, ws_id, command, timeout=30.0):
        calls.append((ws_id, command))
        return 0, ""

    monkeypatch.setattr("portal.devpod.exec.ws_exec", _fake_ws_exec)
    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)

    cred = GitCredential(
        name="gl", host="gitlab.example.com", kind="token", token="tok", username="u"
    )
    src = SourceSpec(url="https://gitlab.example.com/t/repo.git", git_credential="gl")
    await svc._clone_deferred_sources("alice", "alice-ws", [(src, cred)])

    assert len(calls) == 1
    assert calls[0][0] == "alice-ws"
    assert "clone" in calls[0][1]


@pytest.mark.asyncio
async def test_clone_deferred_ssh_reads_key_and_execs(
    monkeypatch, tmp_path: Path, global_cfg, fake_devpod_bin
) -> None:
    calls: list[str] = []

    async def _fake_ws_exec(login, ws_id, command, timeout=30.0):
        calls.append(command)
        return 0, ""

    monkeypatch.setattr("portal.devpod.exec.ws_exec", _fake_ws_exec)
    key_file = tmp_path / "id_ed25519"
    key_file.write_text("SSH-DEPLOY-KEY", encoding="utf-8")
    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)

    cred = GitCredential(name="deploy", host="h", kind="ssh", key_path=str(key_file))
    src = SourceSpec(url="git@h:o/repo.git", git_credential="deploy")
    await svc._clone_deferred_sources("alice", "alice-ws", [(src, cred)])

    assert len(calls) == 1
    assert "GIT_SSH_COMMAND=" in calls[0]
    assert "SSH-DEPLOY-KEY" in calls[0]


@pytest.mark.asyncio
async def test_clone_deferred_ssh_missing_key_skips(
    monkeypatch, global_cfg, fake_devpod_bin
) -> None:
    async def _fake_ws_exec(login, ws_id, command, timeout=30.0):
        raise AssertionError("ws_exec ne doit pas être appelé si la clé est illisible")

    monkeypatch.setattr("portal.devpod.exec.ws_exec", _fake_ws_exec)
    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)

    cred = GitCredential(name="deploy", host="h", kind="ssh", key_path="/nope/missing")
    src = SourceSpec(url="git@h:o/repo.git", git_credential="deploy")
    # OSError sur la lecture de clé → source sautée, pas de crash.
    await svc._clone_deferred_sources("alice", "alice-ws", [(src, cred)])


@pytest.mark.asyncio
async def test_clone_deferred_swallows_ws_exec_errors(
    monkeypatch, global_cfg, fake_devpod_bin
) -> None:
    async def _boom(login, ws_id, command, timeout=30.0):
        raise RuntimeError("tunnel down")

    monkeypatch.setattr("portal.devpod.exec.ws_exec", _boom)
    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)

    cred = GitCredential(name="gl", host="h", kind="token", token="t", username="u")
    src = SourceSpec(url="https://h/t/r.git", git_credential="gl")
    # Ne lève pas : le workspace reste running.
    await svc._clone_deferred_sources("alice", "alice-ws", [(src, cred)])


# --- Durcissement du postCreateCommand inline (pas de panic devpod) ---


def test_inline_clone_disables_devpod_credential_path(
    tmp_data_root: Path, global_cfg, fake_devpod_bin
) -> None:
    import asyncio

    from portal.auth.router import provision_user

    asyncio.run(provision_user(login="alice", sub="sub", data_root=tmp_data_root))
    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    dc_path = svc._write_devcontainer(
        "alice",
        "alice-myapp",
        extra_sources=[SourceSpec(url="https://gitlab.example.com/t/r.git")],
    )
    try:
        content = json.loads(dc_path.read_text(encoding="utf-8"))
        pcc = content["postCreateCommand"]
        assert "GIT_ASKPASS=/bin/false" in pcc
        assert "credential.helper=" in pcc
    finally:
        shutil.rmtree(dc_path.parent, ignore_errors=True)
