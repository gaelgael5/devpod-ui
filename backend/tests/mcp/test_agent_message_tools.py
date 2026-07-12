"""Primitives MCP de messagerie inter-agents (spec 34) — validation + contrat."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from portal.mcp.devpod_tools import agent_message_tools as amt
from portal.mcp.devpod_tools.errors import DevpodToolError

pytestmark = pytest.mark.asyncio

OWNER = "admin"


def _cfg(*names: str):
    return SimpleNamespace(workspaces=[SimpleNamespace(name=n) for n in names])


@pytest.fixture
def patched(monkeypatch):
    """load_user_db renvoie un user avec les workspaces rag/devpod ; amdb mocké."""
    monkeypatch.setattr(amt, "load_user_db", AsyncMock(return_value=_cfg("rag", "devpod")))
    create = AsyncMock(return_value="new-id")
    monkeypatch.setattr(amt.amdb, "create_message", create)
    monkeypatch.setattr(amt.amdb, "get_message", AsyncMock(return_value=None))
    monkeypatch.setattr(amt.amdb, "list_replies", AsyncMock(return_value=[]))
    monkeypatch.setattr(amt.amdb, "list_for_workspace", AsyncMock(return_value=[]))
    return create


# ─── Registre ─────────────────────────────────────────────────────────────────


def test_impls_and_descriptors_in_sync() -> None:
    from portal.mcp.devpod_tools.registry import DEVPOD_PRIMITIVES

    for name in amt.AGENT_MESSAGE_IMPLS:
        assert name in DEVPOD_PRIMITIVES, f"{name} manquant dans DEVPOD_PRIMITIVES"
        assert DEVPOD_PRIMITIVES[name]["scope"] in ("read", "write")


# ─── message_send ─────────────────────────────────────────────────────────────


async def test_send_ok_returns_note(patched) -> None:
    out = await amt._message_send(
        None,
        {"from_workspace": "rag", "to_workspace": "devpod", "subject": "Q", "body": "corps"},
        OWNER,
    )
    assert out["status"] == "pending"
    assert out["message_id"] == "new-id"
    assert "action de l'utilisateur" in out["note"]
    _, kwargs = patched.await_args
    assert kwargs["from_ws_id"] == "admin-rag"
    assert kwargs["to_ws_id"] == "admin-devpod"


async def test_send_rejects_unknown_workspace(patched) -> None:
    with pytest.raises(DevpodToolError, match="to_workspace"):
        await amt._message_send(
            None,
            {"from_workspace": "rag", "to_workspace": "ghost", "subject": "Q", "body": "c"},
            OWNER,
        )


async def test_send_rejects_self(patched) -> None:
    with pytest.raises(DevpodToolError, match="lui-même"):
        await amt._message_send(
            None,
            {"from_workspace": "rag", "to_workspace": "rag", "subject": "Q", "body": "c"},
            OWNER,
        )


async def test_send_rejects_long_subject_and_empty_body(patched) -> None:
    with pytest.raises(DevpodToolError, match="subject"):
        await amt._message_send(
            None,
            {"from_workspace": "rag", "to_workspace": "devpod", "subject": "x" * 201, "body": "c"},
            OWNER,
        )
    with pytest.raises(DevpodToolError, match="body"):
        await amt._message_send(
            None,
            {"from_workspace": "rag", "to_workspace": "devpod", "subject": "Q", "body": ""},
            OWNER,
        )


async def test_reply_to_must_be_a_received_message(patched, monkeypatch) -> None:
    # parent destiné à un AUTRE workspace que l'émetteur → refus
    monkeypatch.setattr(
        amt.amdb,
        "get_message",
        AsyncMock(return_value={"id": "p", "owner_login": OWNER, "to_ws_id": "admin-other"}),
    )
    with pytest.raises(DevpodToolError, match="reply_to"):
        await amt._message_send(
            None,
            {
                "from_workspace": "rag",
                "to_workspace": "devpod",
                "subject": "R",
                "body": "c",
                "reply_to": "p",
            },
            OWNER,
        )


async def test_reply_to_valid_passes_parent_id(patched, monkeypatch) -> None:
    monkeypatch.setattr(
        amt.amdb,
        "get_message",
        AsyncMock(return_value={"id": "p", "owner_login": OWNER, "to_ws_id": "admin-rag"}),
    )
    await amt._message_send(
        None,
        {
            "from_workspace": "rag",
            "to_workspace": "devpod",
            "subject": "R",
            "body": "c",
            "reply_to": "p",
        },
        OWNER,
    )
    assert patched.await_args.kwargs["reply_to"] == "p"


# ─── message_status ───────────────────────────────────────────────────────────


async def test_status_scoped_to_owner(patched, monkeypatch) -> None:
    monkeypatch.setattr(
        amt.amdb, "get_message", AsyncMock(return_value={"id": "m", "owner_login": "mallory"})
    )
    with pytest.raises(DevpodToolError, match="introuvable"):
        await amt._message_status(None, {"message_id": "m"}, OWNER)


# ─── message_list ─────────────────────────────────────────────────────────────


async def test_list_rejects_bad_direction(patched) -> None:
    with pytest.raises(DevpodToolError, match="direction"):
        await amt._message_list(None, {"workspace": "rag", "direction": "weird"}, OWNER)


async def test_list_defaults_to_received(patched) -> None:
    await amt._message_list(None, {"workspace": "rag"}, OWNER)
    assert amt.amdb.list_for_workspace.await_args.kwargs["direction"] == "received"
    assert amt.amdb.list_for_workspace.await_args.kwargs["ws_id"] == "admin-rag"
