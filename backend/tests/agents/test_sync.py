"""Spec 35 §4.2 — construction de l'archive et des scripts de synchronisation host.

Le canal SSH réel est vérifié en bout en bout sur test1 (T8) ; ici on teste les
parties pures : tarball (modes, arcnames), scripts shell (quoting, sémantique).
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from portal.agents.keys import WorkspaceKey
from portal.agents.renderer import build_render_context
from portal.agents.sync import (
    AGENT_CONFIG_ROOT,
    AgentSyncError,
    build_purge_script,
    build_sync_script,
    build_ws_tarball,
)
from portal.agents.tree import generate_workspace_tree


def _stage(tmp_path: Path) -> Path:
    ctx = build_render_context(
        keys=[WorkspaceKey("a1", "p1", "défaut", "mcpk_t1")],
        mcp_url="https://portal.example.org/mcp/",
        ws_id="alice-api",
        workspace_name="api",
        owner_login="alice",
        home="/home/vscode",
        project_root="/workspaces/api",
    )
    agents = [
        {
            "id": "claude",
            "filename": ".mcp.json",
            "template": "c={{ servers | length }}",
            "target_path": "{{ project_root }}/.mcp.json",
        },
        {
            "id": "gemini",
            "filename": "settings.json",
            "template": "g",
            "target_path": "{{ home }}/.gemini/settings.json",
        },
    ]
    return generate_workspace_tree(tmp_path, "alice-api", agents, ctx)


def test_tarball_contents_and_modes(tmp_path: Path) -> None:
    ws_dir = _stage(tmp_path)
    blob = build_ws_tarball(ws_dir)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        members = {m.name: m for m in tf.getmembers()}
    assert "alice-api/claude/.mcp.json" in members
    assert "alice-api/gemini/settings.json" in members
    f = members["alice-api/claude/.mcp.json"]
    assert f.mode & 0o777 == 0o600
    d = members["alice-api/claude"]
    assert d.isdir() and d.mode & 0o777 == 0o700


def test_sync_script_quotes_and_keeps(tmp_path: Path) -> None:
    script = build_sync_script("alice-api", ["claude", "gemini"])
    assert AGENT_CONFIG_ROOT in script
    assert "'alice-api'" in script
    # les agents attendus sont préservés, le reste purgé
    assert "'claude'" in script and "'gemini'" in script
    assert "rm -rf" in script


def test_sync_script_rejects_bad_ids() -> None:
    with pytest.raises(AgentSyncError):
        build_sync_script("alice-api; rm -rf /", ["claude"])
    with pytest.raises(AgentSyncError):
        build_sync_script("alice-api", ["cl$aude"])


def test_purge_script(tmp_path: Path) -> None:
    script = build_purge_script("alice-api")
    assert "rm -rf" in script
    assert "'alice-api'" in script
    with pytest.raises(AgentSyncError):
        build_purge_script("../etc")


def test_sync_script_semantics_local(tmp_path: Path) -> None:
    """Le script joué localement (bash) reproduit la sémantique attendue :
    extraction, perms, remplacement, purge des agents retirés — sans jamais
    recréer le répertoire {ws_id} (inode stable = bind mount préservé)."""
    import subprocess

    ws_dir = _stage(tmp_path)
    blob = build_ws_tarball(ws_dir)
    fake_home = tmp_path / "remote-home"
    fake_home.mkdir()

    def run(script: str, stdin: bytes) -> None:
        subprocess.run(
            ["bash", "-c", script],
            input=stdin,
            check=True,
            env={"HOME": str(fake_home), "PATH": "/usr/bin:/bin"},
        )

    run(build_sync_script("alice-api", ["claude", "gemini"]), blob)
    root = fake_home / ".devpod-portal" / "agent-config"
    target = root / "alice-api"
    assert (target / "claude" / ".mcp.json").read_text() == "c=1"
    assert (target / "gemini" / "settings.json").read_text() == "g"
    inode = target.stat().st_ino

    # resync sans gemini : contenu mis à jour, stale purgé, inode conservé
    (ws_dir / "gemini" / "settings.json").unlink()
    (ws_dir / "gemini").rmdir()
    (ws_dir / "claude" / ".mcp.json").write_text("c=2")
    run(build_sync_script("alice-api", ["claude"]), build_ws_tarball(ws_dir))
    assert (target / "claude" / ".mcp.json").read_text() == "c=2"
    assert not (target / "gemini").exists()
    assert target.stat().st_ino == inode
    # pas de résidu de staging
    assert not list(root.glob(".sync*"))

    run(build_purge_script("alice-api"), b"")
    assert not target.exists()
