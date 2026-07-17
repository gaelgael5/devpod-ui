"""Empreinte de config agents — base du resync idempotent (moins de rotations MCP).

L'empreinte doit refléter TOUT ce qui change les fichiers rendus SAUF le token
(qui rotationne) : profils exposés, définition des agents, url MCP, chemins.
"""

from __future__ import annotations

from portal.agents.sync_state import compute_agent_fingerprint


def _rows(**kw: object) -> list[dict[str, object]]:
    base: dict[str, object] = {
        "id": "claude",
        "template": "T",
        "target_path": "{{ project_root }}/.mcp.json",
        "mode": "replace",
    }
    base.update(kw)
    return [base]


def _fp(**over: object) -> str:
    kwargs: dict[str, object] = {
        "agent_rows": _rows(),
        "profiles": [("p1", "Claude code")],
        "mcp_url": "https://portal/mcp/",
        "project_root": "/workspaces/bob-app",
        "ws_name": "app",
        "owner": "bob",
        "ws_id": "bob-app",
    }
    kwargs.update(over)
    return compute_agent_fingerprint(**kwargs)  # type: ignore[arg-type]


def test_stable_for_identical_inputs() -> None:
    assert _fp() == _fp()


def test_profile_order_does_not_matter() -> None:
    a = _fp(profiles=[("p1", "A"), ("p2", "B")])
    b = _fp(profiles=[("p2", "B"), ("p1", "A")])
    assert a == b


def test_changes_when_profile_set_changes() -> None:
    assert _fp(profiles=[("p1", "Claude code")]) != _fp(profiles=[("p1", "Renamed")])
    assert _fp(profiles=[("p1", "A")]) != _fp(profiles=[("p1", "A"), ("p2", "B")])


def test_changes_when_agent_template_changes() -> None:
    assert _fp(agent_rows=_rows(template="T1")) != _fp(agent_rows=_rows(template="T2"))


def test_changes_when_target_or_mode_changes() -> None:
    assert _fp(agent_rows=_rows(target_path="/a")) != _fp(agent_rows=_rows(target_path="/b"))
    assert _fp(agent_rows=_rows(mode="replace")) != _fp(agent_rows=_rows(mode="merge"))


def test_changes_when_mcp_url_changes() -> None:
    assert _fp(mcp_url="https://a/mcp/") != _fp(mcp_url="https://b/mcp/")


def test_ignores_fields_absent_from_render(  # le token et les colonnes hors rendu
) -> None:
    # Une colonne agent non utilisée au rendu (ex. enabled/filename) ne change rien.
    a = _fp(agent_rows=_rows(enabled=True, filename=".mcp.json"))
    b = _fp(agent_rows=_rows(enabled=False, filename="autre.json"))
    assert a == b
