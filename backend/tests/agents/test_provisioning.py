"""Spec 35 §8.5 — builders purs de l'intégration provisioning (mount, postCreate)."""

from __future__ import annotations

import pytest

from portal.agents.provisioning import (
    AGENT_MOUNT_TARGET,
    AgentProvisionError,
    build_agent_mount,
    build_agent_post_create,
)


def _claude_row() -> dict[str, object]:
    return {
        "id": "claude",
        "filename": ".mcp.json",
        "template": "{}",
        "target_path": "{{ project_root }}/.mcp.json",
        "enabled": True,
    }


def _gemini_row() -> dict[str, object]:
    return {
        "id": "gemini",
        "filename": "settings.json",
        "template": "{}",
        "target_path": "{{ home }}/.gemini/settings.json",
        "enabled": True,
    }


def test_build_agent_mount() -> None:
    mount = build_agent_mount("/home/debian", "alice-api")
    assert mount == (
        "source=/home/debian/.devpod-portal/agent-config/alice-api,"
        f"target={AGENT_MOUNT_TARGET},type=bind,readonly"
    )


def test_build_agent_mount_rejects_bad_input() -> None:
    with pytest.raises(AgentProvisionError):
        build_agent_mount("", "alice-api")
    with pytest.raises(AgentProvisionError):
        build_agent_mount("/home/debian", "../etc")


def test_post_create_symlink_project_root_with_git_exclude() -> None:
    cmds = build_agent_post_create([_claude_row()], project_root="/workspaces/alice-api")
    joined = " && ".join(cmds)
    link = f'ln -sfn "{AGENT_MOUNT_TARGET}/claude/.mcp.json" "/workspaces/alice-api/.mcp.json"'
    assert link in joined
    # le repo de l'utilisateur reste propre : exclusion locale, jamais .gitignore
    assert ".git/info/exclude" in joined
    assert "/.mcp.json" in joined


def test_post_create_symlink_home_target_no_git_exclude() -> None:
    cmds = build_agent_post_create([_gemini_row()], project_root="/workspaces/alice-api")
    joined = " && ".join(cmds)
    link = f'ln -sfn "{AGENT_MOUNT_TARGET}/gemini/settings.json" "$HOME/.gemini/settings.json"'
    assert link in joined
    assert ".git/info/exclude" not in joined
    # le parent du target est créé avant le lien
    assert 'mkdir -p "$(dirname "$HOME/.gemini/settings.json")"' in joined


def test_post_create_rejects_relative_or_traversal_target() -> None:
    row = _claude_row()
    row["target_path"] = "relative/path.json"
    with pytest.raises(AgentProvisionError):
        build_agent_post_create([row], project_root="/workspaces/x")
    row["target_path"] = "{{ project_root }}/{{ workspace.name }}/../../etc/x"
    with pytest.raises(AgentProvisionError):
        build_agent_post_create(
            [row], project_root="/workspaces/x", workspace={"id": "a-x", "name": "x", "owner": "a"}
        )


def test_post_create_rejects_quote_injection_in_rendered_target() -> None:
    row = _claude_row()
    row["target_path"] = '{{ project_root }}/a"; rm -rf /; echo ".json'
    with pytest.raises(AgentProvisionError):
        build_agent_post_create([row], project_root="/workspaces/x")


def test_post_create_broken_target_template() -> None:
    row = _claude_row()
    row["target_path"] = "{{ nope }}/x.json"
    with pytest.raises(AgentProvisionError):
        build_agent_post_create([row], project_root="/workspaces/x")


async def test_sync_rejects_relative_mcp_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """external_url absente → URL relative → fail explicite, pas de config morte."""
    from portal.agents.provisioning import sync_agent_config

    with pytest.raises(AgentProvisionError, match="external_url"):
        await sync_agent_config(
            login="alice",
            ws_id="alice-api",
            ws_name="api",
            agent_rows=[_claude_row()],
            ssh_user="root",
            ssh_host="h",
            ssh_key_path="/k",
            mcp_url="/mcp/",
            project_root="/workspaces/alice-api",
        )
