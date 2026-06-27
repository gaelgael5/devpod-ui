from __future__ import annotations

import uuid

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp_audit import list_for_owner, record
from portal.db.tables import users


async def test_audit_record_and_list(db_conn: AsyncConnection) -> None:
    await db_conn.execute(
        insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
    )
    await record(
        db_conn,
        apikey_id="a1",
        owner_login="alice",
        namespaced_name="rag__search",
        backend_id="b1",
        backend_key_id="k1",
        latency_ms=42,
        status="ok",
        error=None,
    )
    rows = await list_for_owner(db_conn, "alice")
    assert len(rows) == 1
    assert rows[0]["status"] == "ok"
    assert rows[0]["namespaced_name"] == "rag__search"
