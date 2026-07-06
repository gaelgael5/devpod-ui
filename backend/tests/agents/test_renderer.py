"""Spec 35 §8.2 — rendu Jinja sandboxé des fichiers de configuration agents."""

from __future__ import annotations

import json

import pytest

from portal.agents.keys import WorkspaceKey
from portal.agents.renderer import (
    AgentRenderError,
    build_render_context,
    render_agent_file,
)

CLAUDE_TEMPLATE = """\
{
  "mcpServers": {
{%- for s in servers %}
    {{ s.name | tojson }}: {
      "type": "http",
      "url": {{ s.url | tojson }},
      "headers": {"Authorization": {{ ("Bearer " ~ s.token) | tojson }}}
    }{{ "," if not loop.last }}
{%- endfor %}
  }
}
"""


def _ctx(keys: list[WorkspaceKey] | None = None) -> dict[str, object]:
    return build_render_context(
        keys=keys
        if keys is not None
        else [
            WorkspaceKey("a1", "p1", "Lecture seule", "mcpk_tok1"),
            WorkspaceKey("a2", "p2", "admin", "mcpk_tok2"),
        ],
        mcp_url="https://portal.example.org/mcp/",
        ws_id="alice-api",
        workspace_name="api",
        owner_login="alice",
        home="/home/vscode",
        project_root="/workspaces/api",
    )


def test_render_claude_template_valid_json() -> None:
    out = render_agent_file(CLAUDE_TEMPLATE, _ctx())
    data = json.loads(out)
    servers = data["mcpServers"]
    assert set(servers) == {"lecture-seule", "admin"}
    assert servers["lecture-seule"]["url"] == "https://portal.example.org/mcp/"
    assert servers["lecture-seule"]["headers"]["Authorization"] == "Bearer mcpk_tok1"
    assert servers["admin"]["headers"]["Authorization"] == "Bearer mcpk_tok2"


def test_render_no_servers_yields_empty_block() -> None:
    out = render_agent_file(CLAUDE_TEMPLATE, _ctx(keys=[]))
    assert json.loads(out) == {"mcpServers": {}}


def test_context_slug_collision_deduplicated() -> None:
    ctx = _ctx(
        keys=[
            WorkspaceKey("a1", "p1", "Défaut", "mcpk_t1"),
            WorkspaceKey("a2", "p2", "défaut", "mcpk_t2"),
        ]
    )
    names = [s["name"] for s in ctx["servers"]]  # type: ignore[index]
    assert len(names) == len(set(names)) == 2
    assert all(n for n in names)


def test_context_exposes_workspace_metadata() -> None:
    ctx = _ctx()
    assert ctx["workspace"] == {"id": "alice-api", "name": "api", "owner": "alice"}
    assert ctx["home"] == "/home/vscode"
    assert ctx["project_root"] == "/workspaces/api"


def test_hostile_template_sandboxed() -> None:
    for hostile in (
        "{{ ''.__class__.__mro__ }}",
        "{{ servers.__init__.__globals__ }}",
        "{{ cycler.__init__.__globals__ }}",
    ):
        with pytest.raises(AgentRenderError):
            render_agent_file(hostile, _ctx())


def test_undefined_variable_rejected() -> None:
    with pytest.raises(AgentRenderError):
        render_agent_file("{{ nope }}", _ctx())


def test_syntax_error_rejected() -> None:
    with pytest.raises(AgentRenderError):
        render_agent_file("{% for %}", _ctx())


def test_render_error_never_leaks_tokens() -> None:
    ctx = _ctx()
    try:
        render_agent_file("{{ servers[0].token.no_such_attr() }}", ctx)
    except AgentRenderError as exc:
        assert "mcpk_tok1" not in str(exc)
    else:  # le sandbox peut aussi rendre sans erreur — dans ce cas rien à vérifier
        pass
