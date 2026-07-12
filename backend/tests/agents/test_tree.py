"""Spec 35 §8.4 — construction de l'arborescence agent-config (perms, atomicité, stales)."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from portal.agents.keys import WorkspaceKey
from portal.agents.renderer import build_render_context
from portal.agents.tree import AgentTreeError, generate_workspace_tree


def _agent(aid: str = "claude", template: str = "servers={{ servers | length }}") -> dict:
    return {
        "id": aid,
        "label": aid,
        "filename": ".mcp.json",
        "template": template,
        "target_path": "{{ project_root }}/.mcp.json",
        "enabled": True,
    }


def _ctx() -> dict[str, object]:
    return build_render_context(
        keys=[WorkspaceKey("a1", "p1", "défaut", "mcpk_t1")],
        mcp_url="https://portal.example.org/mcp/",
        ws_id="alice-api",
        workspace_name="api",
        owner_login="alice",
        home="/home/vscode",
        project_root="/workspaces/api",
    )


def test_generate_tree_nominal(tmp_path: Path) -> None:
    ws_dir = generate_workspace_tree(tmp_path, "alice-api", [_agent()], _ctx())
    assert ws_dir == tmp_path / "alice-api"
    f = ws_dir / "claude" / ".mcp.json"
    assert f.read_text() == "servers=1"
    assert stat.S_IMODE(ws_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(f.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(f.stat().st_mode) == 0o600


def test_generate_tree_keeps_ws_dir_inode(tmp_path: Path) -> None:
    """Le répertoire {ws_id} est un point de montage bind : il ne doit JAMAIS être
    recréé (le mount du conteneur resterait épinglé sur l'ancien inode)."""
    ws_dir = generate_workspace_tree(tmp_path, "alice-api", [_agent()], _ctx())
    inode = ws_dir.stat().st_ino
    generate_workspace_tree(tmp_path, "alice-api", [_agent()], _ctx())
    assert ws_dir.stat().st_ino == inode


def test_generate_tree_removes_stale_agents(tmp_path: Path) -> None:
    generate_workspace_tree(tmp_path, "alice-api", [_agent("claude"), _agent("gemini")], _ctx())
    ws_dir = generate_workspace_tree(tmp_path, "alice-api", [_agent("claude")], _ctx())
    assert (ws_dir / "claude" / ".mcp.json").exists()
    assert not (ws_dir / "gemini").exists()


def test_generate_tree_empty_agents_empties_dir(tmp_path: Path) -> None:
    generate_workspace_tree(tmp_path, "alice-api", [_agent()], _ctx())
    ws_dir = generate_workspace_tree(tmp_path, "alice-api", [], _ctx())
    assert ws_dir.exists()
    assert list(ws_dir.iterdir()) == []


@pytest.mark.parametrize("bad_ws", ["", "..", "a/b", "A-api", "-x", "x" * 100, ".hidden"])
def test_generate_tree_rejects_bad_ws_id(tmp_path: Path, bad_ws: str) -> None:
    with pytest.raises(AgentTreeError):
        generate_workspace_tree(tmp_path, bad_ws, [_agent()], _ctx())


def test_generate_tree_rejects_bad_agent_parts(tmp_path: Path) -> None:
    with pytest.raises(AgentTreeError):
        generate_workspace_tree(tmp_path, "alice-api", [_agent("../evil")], _ctx())
    bad_filename = _agent()
    bad_filename["filename"] = "../evil"
    with pytest.raises(AgentTreeError):
        generate_workspace_tree(tmp_path, "alice-api", [bad_filename], _ctx())


def test_generate_tree_render_error_leaves_previous_content(tmp_path: Path) -> None:
    """Un template cassé ne doit pas corrompre le fichier existant (écriture atomique)."""
    generate_workspace_tree(tmp_path, "alice-api", [_agent()], _ctx())
    f = tmp_path / "alice-api" / "claude" / ".mcp.json"
    before = f.read_text()
    with pytest.raises(AgentTreeError):
        generate_workspace_tree(tmp_path, "alice-api", [_agent(template="{{ nope }}")], _ctx())
    assert f.read_text() == before
