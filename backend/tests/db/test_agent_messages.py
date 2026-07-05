"""Couche db de la messagerie inter-agents (spec 34, table agent_messages)."""
from __future__ import annotations

import pytest

from portal.db import agent_messages as am

pytestmark = pytest.mark.asyncio

OWNER = "admin"
A = "admin-rag"
B = "admin-devpod"


async def _mk(db_conn, **kw) -> str:
    base = dict(owner_login=OWNER, from_ws_id=A, to_ws_id=B, subject="Q", body="corps")
    base.update(kw)
    return await am.create_message(db_conn, **base)


async def test_create_and_get(db_conn) -> None:
    mid = await _mk(db_conn, subject="Contrat API", body="Quel format ?")
    got = await am.get_message(db_conn, mid)
    assert got is not None
    assert got["status"] == "pending"
    assert got["from_ws_id"] == A and got["to_ws_id"] == B
    assert got["subject"] == "Contrat API"
    assert got["delivered_at"] is None


async def test_received_hides_pending_shows_delivered(db_conn) -> None:
    """Un agent destinataire ne voit jamais les pending ; seulement les delivered."""
    pending = await _mk(db_conn)
    delivered = await _mk(db_conn, subject="livré")
    assert await am.mark_delivered(db_conn, delivered, OWNER, "main") is True

    recv = await am.list_for_workspace(db_conn, owner_login=OWNER, ws_id=B, direction="received")
    ids = {m["id"] for m in recv}
    assert delivered in ids
    assert pending not in ids


async def test_sent_shows_all_statuses(db_conn) -> None:
    m1 = await _mk(db_conn)
    m2 = await _mk(db_conn)
    await am.mark_cancelled(db_conn, m2, OWNER)
    sent = await am.list_for_workspace(db_conn, owner_login=OWNER, ws_id=A, direction="sent")
    ids = {m["id"] for m in sent}
    assert {m1, m2} <= ids


async def test_delivery_transition_optimistic(db_conn) -> None:
    mid = await _mk(db_conn)
    # première délivrance gagne
    assert await am.mark_delivered(db_conn, mid, OWNER, "main") is True
    got = await am.get_message(db_conn, mid)
    assert got["status"] == "delivered"
    assert got["delivered_to_session"] == "main"
    assert got["delivered_at"] is not None
    # re-délivrance / annulation refusées (message immuable)
    assert await am.mark_delivered(db_conn, mid, OWNER, "other") is False
    assert await am.mark_cancelled(db_conn, mid, OWNER) is False


async def test_cancel_then_no_deliver(db_conn) -> None:
    mid = await _mk(db_conn)
    assert await am.mark_cancelled(db_conn, mid, OWNER) is True
    assert await am.get_message(db_conn, mid)["status"] == "cancelled"
    assert await am.mark_delivered(db_conn, mid, OWNER, "main") is False


async def test_owner_scoping_blocks_foreign(db_conn) -> None:
    """Un autre owner ne peut ni délivrer ni annuler le message."""
    mid = await _mk(db_conn)
    assert await am.mark_delivered(db_conn, mid, "mallory", "main") is False
    assert await am.mark_cancelled(db_conn, mid, "mallory") is False
    assert await am.get_message(db_conn, mid)["status"] == "pending"


async def test_pending_list_and_count(db_conn) -> None:
    await _mk(db_conn, to_ws_id=B)
    await _mk(db_conn, to_ws_id=B)
    await _mk(db_conn, from_ws_id=B, to_ws_id=A)
    delivered = await _mk(db_conn, to_ws_id=B)
    await am.mark_delivered(db_conn, delivered, OWNER, "main")

    pending = await am.list_pending(db_conn, OWNER)
    assert all(m["status"] == "pending" for m in pending)
    assert len(pending) == 3  # le delivered exclu

    counts = await am.count_pending_by_to_ws(db_conn, OWNER)
    assert counts == {B: 2, A: 1}


async def test_reply_thread(db_conn) -> None:
    q = await _mk(db_conn, from_ws_id=A, to_ws_id=B)
    r = await _mk(db_conn, from_ws_id=B, to_ws_id=A, reply_to=q)
    replies = await am.list_replies(db_conn, q)
    assert [x["message_id"] for x in replies] == [r]
    assert replies[0]["status"] == "pending"


async def test_self_send_rejected_by_check(db_conn) -> None:
    """La contrainte CHECK interdit un auto-envoi (from == to)."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await am.create_message(
            db_conn, owner_login=OWNER, from_ws_id=A, to_ws_id=A, subject="x", body="y"
        )
