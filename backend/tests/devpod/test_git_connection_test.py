"""Tests du test de connexion d'un credential git (sans dépôt réel)."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import portal.devpod.git as git_mod
from portal.devpod.git import probe_git_credential


@pytest.mark.asyncio
async def test_success_when_returncode_zero(monkeypatch) -> None:
    monkeypatch.setattr(git_mod, "run_git_ls_remote", AsyncMock(return_value=(0, b"", b"")))
    ok, _msg = await probe_git_credential("cred1", "github.com", "alice")
    assert ok is True


@pytest.mark.asyncio
async def test_success_when_repository_not_found_after_auth(monkeypatch) -> None:
    # Auth réussie, la sonde synthétique n'existe simplement pas — succès attendu.
    monkeypatch.setattr(
        git_mod,
        "run_git_ls_remote",
        AsyncMock(return_value=(128, b"", b"remote: Repository not found.\nfatal: ...")),
    )
    ok, msg = await probe_git_credential("cred1", "github.com", "alice")
    assert ok is True
    assert "not found" in msg.lower()


@pytest.mark.asyncio
async def test_success_when_does_not_exist(monkeypatch) -> None:
    monkeypatch.setattr(
        git_mod,
        "run_git_ls_remote",
        AsyncMock(return_value=(128, b"", b"fatal: 'x.git' does not exist")),
    )
    ok, _msg = await probe_git_credential("cred1", "gitlab.com", "alice")
    assert ok is True


@pytest.mark.asyncio
async def test_failure_on_permission_denied(monkeypatch) -> None:
    monkeypatch.setattr(
        git_mod,
        "run_git_ls_remote",
        AsyncMock(return_value=(128, b"", b"git@github.com: Permission denied (publickey).")),
    )
    ok, msg = await probe_git_credential("cred1", "github.com", "alice")
    assert ok is False
    assert "permission denied" in msg.lower()


@pytest.mark.asyncio
async def test_failure_on_http_authentication_failed(monkeypatch) -> None:
    monkeypatch.setattr(
        git_mod,
        "run_git_ls_remote",
        AsyncMock(
            return_value=(
                128,
                b"",
                b"remote: Invalid username or password.\nfatal: Authentication failed",
            )
        ),
    )
    ok, _msg = await probe_git_credential("cred1", "gitlab.com", "alice")
    assert ok is False


@pytest.mark.asyncio
async def test_failure_on_connection_refused(monkeypatch) -> None:
    monkeypatch.setattr(
        git_mod,
        "run_git_ls_remote",
        AsyncMock(
            return_value=(128, b"", b"ssh: connect to host github.com port 22: Connection refused")
        ),
    )
    ok, _msg = await probe_git_credential("cred1", "github.com", "alice")
    assert ok is False


@pytest.mark.asyncio
async def test_failure_on_unknown_error_defaults_closed(monkeypatch) -> None:
    # Erreur non reconnue → échec par défaut (jamais de faux positif).
    monkeypatch.setattr(
        git_mod,
        "run_git_ls_remote",
        AsyncMock(return_value=(1, b"", b"something weird happened")),
    )
    ok, _msg = await probe_git_credential("cred1", "github.com", "alice")
    assert ok is False


@pytest.mark.asyncio
async def test_propagates_http_exception_as_failure(monkeypatch) -> None:
    from fastapi import HTTPException

    async def _raise(*a: object, **kw: object) -> tuple[int, bytes, bytes]:
        raise HTTPException(status_code=422, detail="Hostname introuvable : 'bogus'")

    monkeypatch.setattr(git_mod, "run_git_ls_remote", _raise)
    ok, msg = await probe_git_credential("cred1", "bogus", "alice")
    assert ok is False
    assert "bogus" in msg


@pytest.mark.asyncio
async def test_probe_uses_synthetic_path_on_credential_host(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _fake(url: str, credential_name: str, login: str) -> tuple[int, bytes, bytes]:
        captured["url"] = url
        captured["credential_name"] = credential_name
        captured["login"] = login
        return 0, b"", b""

    monkeypatch.setattr(git_mod, "run_git_ls_remote", _fake)
    await probe_git_credential("cred1", "github.com", "alice")

    assert captured["credential_name"] == "cred1"
    assert captured["login"] == "alice"
    assert "github.com" in str(captured["url"])
