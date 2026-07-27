"""Rotation d'une clef API MCP (ticket 716556e8).

- Clef manuelle (bearer) : révocation immédiate + nouvelle clef même label/profil,
  token clair retourné une seule fois (one-time reveal côté UI).
- Clef workspace (Claude Code) : rotation + réinjection via push_agent_files —
  jamais de reveal — orchestrée par agents.push.rotate_workspace_and_push,
  refusée si le workspace n'est pas running.
"""

from __future__ import annotations

from typing import Any

import pytest

from portal.mcp import service as msvc


def _stub_db(monkeypatch: pytest.MonkeyPatch, row: dict[str, Any] | None) -> dict[str, Any]:
    """Stubbe la couche db du service ; retourne le journal des appels."""
    calls: dict[str, Any] = {"revoked": [], "inserted": []}

    async def _get(conn: Any, owner: str, aid: str) -> dict[str, Any] | None:
        return row

    async def _revoke(conn: Any, owner: str, aid: str) -> bool:
        calls["revoked"].append(aid)
        return True

    async def _insert(conn: Any, **kw: Any) -> None:
        calls["inserted"].append(kw)

    monkeypatch.setattr(msvc.db, "get_apikey", _get)
    monkeypatch.setattr(msvc.db, "revoke_apikey", _revoke)
    monkeypatch.setattr(msvc.db, "insert_apikey", _insert)
    return calls


@pytest.mark.asyncio
async def test_rotate_revokes_old_and_creates_new_with_same_label_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_db(
        monkeypatch,
        {
            "id": "old-id",
            "label": "mon-client",
            "profile_id": "prof-1",
            "workspace_ref": None,
            "revoked": False,
            "kind": "apikey",
        },
    )
    new_id, clear = await msvc.rotate_apikey(object(), "alice", "old-id")

    assert calls["revoked"] == ["old-id"]
    assert len(calls["inserted"]) == 1
    ins = calls["inserted"][0]
    assert ins["label"] == "mon-client"
    assert ins["profile_id"] == "prof-1"
    assert ins["id"] == new_id != "old-id"
    # Le token clair est retourné (one-time) mais jamais stocké en clair.
    assert clear.startswith(msvc.APIKEY_PREFIX)
    assert ins["token_hash"] != clear


@pytest.mark.asyncio
async def test_rotate_unknown_key_raises_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_db(monkeypatch, None)
    with pytest.raises(msvc.NotFound):
        await msvc.rotate_apikey(object(), "alice", "nope")


@pytest.mark.asyncio
async def test_rotate_rejects_workspace_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Les clefs workspace ont leur propre cycle (réinjection) — pas ce chemin."""
    _stub_db(
        monkeypatch,
        {
            "id": "k",
            "label": "ws:alice-ws/dev",
            "profile_id": "p",
            "workspace_ref": "alice-ws",
            "revoked": False,
            "kind": "apikey",
        },
    )
    with pytest.raises(msvc.InvalidReference):
        await msvc.rotate_apikey(object(), "alice", "k")


@pytest.mark.asyncio
async def test_rotate_rejects_revoked_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_db(
        monkeypatch,
        {
            "id": "k",
            "label": "x",
            "profile_id": None,
            "workspace_ref": None,
            "revoked": True,
            "kind": "apikey",
        },
    )
    with pytest.raises(msvc.InvalidReference):
        await msvc.rotate_apikey(object(), "alice", "k")


@pytest.mark.asyncio
async def test_rotate_rejects_oauth_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_db(
        monkeypatch,
        {
            "id": "k",
            "label": "x",
            "profile_id": None,
            "workspace_ref": None,
            "revoked": False,
            "kind": "oauth",
        },
    )
    with pytest.raises(msvc.InvalidReference):
        await msvc.rotate_apikey(object(), "alice", "k")


# ─── Orchestration workspace : rotation + réinjection ─────────────────────────


@pytest.mark.asyncio
async def test_rotate_workspace_and_push_requires_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from portal.agents import push as apush

    async def _status(login: str, ws_id: str) -> dict[str, Any]:
        return {"status": "stopped"}

    monkeypatch.setattr(apush, "_workspace_status", _status)
    with pytest.raises(apush.AgentProvisionError, match="running"):
        await apush.rotate_workspace_and_push("alice", "alice-ws")


@pytest.mark.asyncio
async def test_rotate_workspace_and_push_forces_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L'empreinte de livraison est oubliée AVANT le push : la re-livraison (et
    donc la rotation des clefs) est forcée même à config inchangée."""
    from portal.agents import push as apush

    order: list[str] = []

    async def _status(login: str, ws_id: str) -> dict[str, Any]:
        return {"status": "running"}

    async def _forget(ws_id: str) -> None:
        order.append(f"forget:{ws_id}")

    async def _params(login: str, ws_id: str) -> dict[str, Any]:
        return {
            "agents": ["claude"],
            "mcp_url": "https://portal.example/mcp/",
            "ws_name": "ws",
            "project_root": "/workspaces/alice-ws",
        }

    async def _push(**kw: Any) -> list[str]:
        order.append(f"push:{kw['ws_id']}")
        return ["claude"]

    monkeypatch.setattr(apush, "_workspace_status", _status)
    monkeypatch.setattr(apush, "_forget_config_hash", _forget)
    monkeypatch.setattr(apush, "_workspace_push_params", _params)
    monkeypatch.setattr(apush, "push_agent_files", _push)

    pushed = await apush.rotate_workspace_and_push("alice", "alice-ws")
    assert pushed == ["claude"]
    assert order == ["forget:alice-ws", "push:alice-ws"]


@pytest.mark.asyncio
async def test_rotate_workspace_and_push_requires_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sans agent configuré, rien ne consommerait le nouveau token : refus clair."""
    from portal.agents import push as apush

    async def _status(login: str, ws_id: str) -> dict[str, Any]:
        return {"status": "running"}

    async def _params(login: str, ws_id: str) -> dict[str, Any]:
        return {
            "agents": [],
            "mcp_url": "https://portal.example/mcp/",
            "ws_name": "ws",
            "project_root": "/workspaces/alice-ws",
        }

    monkeypatch.setattr(apush, "_workspace_status", _status)
    monkeypatch.setattr(apush, "_workspace_push_params", _params)
    with pytest.raises(apush.AgentProvisionError, match="agent"):
        await apush.rotate_workspace_and_push("alice", "alice-ws")
