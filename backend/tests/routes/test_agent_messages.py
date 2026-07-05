"""Endpoints REST + mécanisme de délivrance de la messagerie inter-agents (spec 34).

Handlers appelés directement avec conn factice ; db et session I/O mockés."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import portal.routes.agent_messages as rt
from portal.auth.rbac import UserInfo
from portal.mcp.devpod_tools.errors import DevpodToolError

pytestmark = pytest.mark.asyncio

USER = UserInfo(login="admin", roles=["dev"])
CONN = object()


def _msg(**kw):
    base = {
        "id": "m1",
        "owner_login": "admin",
        "from_ws_id": "admin-rag",
        "to_ws_id": "admin-devpod",
        "subject": "Contrat API",
        "body": "Quel format ?",
        "status": "pending",
    }
    base.update(kw)
    return base


@pytest.fixture
def db(monkeypatch):
    m = AsyncMock()
    monkeypatch.setattr(rt.amdb, "get_message", m.get_message)
    monkeypatch.setattr(rt.amdb, "mark_delivered", m.mark_delivered)
    monkeypatch.setattr(rt.amdb, "mark_cancelled", m.mark_cancelled)
    monkeypatch.setattr(rt.amdb, "list_replies", AsyncMock(return_value=[]))
    monkeypatch.setattr(rt.amdb, "list_pending", m.list_pending)
    monkeypatch.setattr(rt.amdb, "count_pending_by_to_ws", m.count)
    return m


@pytest.fixture
def sess(monkeypatch):
    get = AsyncMock(return_value={"processing": False, "alive": True})
    send = AsyncMock(return_value={"sent": True})
    monkeypatch.setattr(rt, "_session_get", get)
    monkeypatch.setattr(rt, "_session_send", send)
    return get, send


# ─── liste / détail / badge ───────────────────────────────────────────────────


async def test_list_derives_names(db) -> None:
    db.list_pending.return_value = [_msg()]
    out = await rt.list_agent_messages(status="pending", user=USER, conn=CONN)
    assert out[0]["from_name"] == "rag" and out[0]["to_name"] == "devpod"


async def test_pending_counts_by_name(db) -> None:
    db.count.return_value = {"admin-devpod": 2, "admin-rag": 1}
    out = await rt.pending_counts(user=USER, conn=CONN)
    assert out == {"devpod": 2, "rag": 1}


async def test_detail_404_when_foreign(db) -> None:
    db.get_message.return_value = _msg(owner_login="mallory")
    with pytest.raises(HTTPException) as e:
        await rt.get_agent_message("m1", user=USER, conn=CONN)
    assert e.value.status_code == 404


# ─── délivrance ───────────────────────────────────────────────────────────────


async def test_deliver_happy_path_injects_then_marks(db, sess) -> None:
    get, send = sess
    db.get_message.return_value = _msg()
    db.mark_delivered.return_value = True

    out = await rt.deliver_agent_message(
        "m1", rt.DeliverBody(session="main"), user=USER, conn=CONN
    )
    assert out == {"status": "delivered", "delivered_to_session": "main"}
    # injection sur le bon workspace + framing contient l'id et le sujet
    send.assert_awaited_once()
    sent_args = send.await_args.args[1]
    assert sent_args["workspace"] == "devpod"
    assert 'reply_to="m1"' in sent_args["text"]
    assert "Contrat API" in sent_args["text"]
    # ordre : injection AVANT le mark_delivered
    db.mark_delivered.assert_awaited_once()


async def test_deliver_409_when_not_pending(db, sess) -> None:
    db.get_message.return_value = _msg(status="delivered")
    with pytest.raises(HTTPException) as e:
        await rt.deliver_agent_message("m1", rt.DeliverBody(session="main"), user=USER, conn=CONN)
    assert e.value.status_code == 409
    sess[1].assert_not_awaited()  # aucune injection


async def test_deliver_409_when_session_busy(db, sess) -> None:
    get, send = sess
    db.get_message.return_value = _msg()
    get.return_value = {"processing": True, "alive": True}
    with pytest.raises(HTTPException) as e:
        await rt.deliver_agent_message("m1", rt.DeliverBody(session="main"), user=USER, conn=CONN)
    assert e.value.status_code == 409 and "occupée" in e.value.detail
    send.assert_not_awaited()
    db.mark_delivered.assert_not_awaited()


async def test_deliver_404_when_session_absent(db, sess) -> None:
    get, send = sess
    db.get_message.return_value = _msg()
    get.side_effect = DevpodToolError("session introuvable")
    with pytest.raises(HTTPException) as e:
        await rt.deliver_agent_message("m1", rt.DeliverBody(session="x"), user=USER, conn=CONN)
    assert e.value.status_code == 404
    send.assert_not_awaited()


async def test_deliver_injection_failure_keeps_pending(db, sess) -> None:
    get, send = sess
    db.get_message.return_value = _msg()
    send.side_effect = DevpodToolError("session morte")
    with pytest.raises(HTTPException) as e:
        await rt.deliver_agent_message("m1", rt.DeliverBody(session="main"), user=USER, conn=CONN)
    assert e.value.status_code == 409
    db.mark_delivered.assert_not_awaited()  # reste pending


# ─── rejet ────────────────────────────────────────────────────────────────────


async def test_cancel_ok(db) -> None:
    db.get_message.return_value = _msg()
    db.mark_cancelled.return_value = True
    out = await rt.cancel_agent_message("m1", user=USER, conn=CONN)
    assert out == {"status": "cancelled"}


async def test_cancel_409_when_not_pending(db) -> None:
    db.get_message.return_value = _msg(status="delivered")
    db.mark_cancelled.return_value = False
    with pytest.raises(HTTPException) as e:
        await rt.cancel_agent_message("m1", user=USER, conn=CONN)
    assert e.value.status_code == 409
