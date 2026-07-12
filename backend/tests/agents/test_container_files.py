"""Spec 35b T3 — canal fichier conteneur (read/write atomique via `ws_exec`).

Le mode `merge` lit le fichier partagé DANS le conteneur, le fusionne côté portail,
puis le réécrit atomiquement. Ce module ne fait ni merge ni SSH bas niveau : il
s'appuie sur la façade `ws_exec` (devpod/exec.py) et encode le contenu en base64
pour traverser le shell distant sans quoting fragile ni corruption binaire.
"""

from __future__ import annotations

import base64

import pytest

from portal.agents import container_files
from portal.agents.container_files import (
    ContainerFileError,
    read_container_file,
    write_container_file,
)


class _FakeExec:
    """Capture les appels à ws_exec et renvoie une réponse scriptée."""

    def __init__(self, rc: int = 0, output: str = "") -> None:
        self.rc = rc
        self.output = output
        self.calls: list[tuple[str, str, str, float]] = []

    async def __call__(
        self, login: str, ws_id: str, command: str, timeout: float = 30.0
    ) -> tuple[int, str]:
        self.calls.append((login, ws_id, command, timeout))
        return self.rc, self.output


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


# ── read ──────────────────────────────────────────────────────────────────


async def test_read_present_decodes_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeExec(0, _b64('{"mcpServers": {}}'))
    monkeypatch.setattr(container_files, "ws_exec", fake)

    content = await read_container_file("bob", "bob-app", "/home/vscode/.mcp.json")

    assert content == '{"mcpServers": {}}'
    # cat côté conteneur : chemin quoté, aucune valeur libre dans le shell.
    assert "/home/vscode/.mcp.json" in fake.calls[0][2]


async def test_read_absent_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # Sentinelle `NOFILE` (6 chars, jamais une sortie base64 valide) = fichier absent.
    fake = _FakeExec(0, "NOFILE")
    monkeypatch.setattr(container_files, "ws_exec", fake)

    assert await read_container_file("bob", "bob-app", "/home/vscode/.absent") is None


async def test_read_empty_file_returns_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fichier présent mais vide : base64("") == "" — à distinguer de l'absence.
    fake = _FakeExec(0, "")
    monkeypatch.setattr(container_files, "ws_exec", fake)

    assert await read_container_file("bob", "bob-app", "/home/vscode/.empty") == ""


async def test_read_unicode_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    original = '# réglage café\n[mcp_servers.perso]\nurl = "wss://é.example"\n'
    fake = _FakeExec(0, _b64(original))
    monkeypatch.setattr(container_files, "ws_exec", fake)

    assert await read_container_file("bob", "bob-app", "/x") == original


async def test_read_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeExec(1, "cat: permission denied")
    monkeypatch.setattr(container_files, "ws_exec", fake)

    with pytest.raises(ContainerFileError):
        await read_container_file("bob", "bob-app", "/root/secret")


# ── write ─────────────────────────────────────────────────────────────────


async def test_write_atomic_command_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeExec(0, "")
    monkeypatch.setattr(container_files, "ws_exec", fake)

    content = '{"mcpServers": {"portal-default": {}}}'
    await write_container_file("bob", "bob-app", "/home/vscode/.codex/config.toml", content)

    cmd = fake.calls[0][2]
    # mkdir du parent + décodage base64 + perms 600 + rename atomique.
    assert "mkdir -p" in cmd
    assert "/home/vscode/.codex" in cmd
    assert "base64 -d" in cmd
    assert "chmod 600" in cmd
    assert "mv " in cmd
    # le contenu voyage encodé, jamais en clair dans la ligne de commande.
    assert _b64(content) in cmd
    assert content not in cmd


async def test_write_targets_final_path(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeExec(0, "")
    monkeypatch.setattr(container_files, "ws_exec", fake)

    await write_container_file("bob", "bob-app", "/home/vscode/.mcp.json", "{}")

    assert "/home/vscode/.mcp.json" in fake.calls[0][2]
    assert fake.calls[0][0] == "bob"
    assert fake.calls[0][1] == "bob-app"


async def test_write_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeExec(1, "mv: read-only file system")
    monkeypatch.setattr(container_files, "ws_exec", fake)

    with pytest.raises(ContainerFileError):
        await write_container_file("bob", "bob-app", "/x", "{}")
