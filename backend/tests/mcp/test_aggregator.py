from __future__ import annotations

import uuid

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import insert_apikey, set_grant
from portal.db.mcp_catalog import upsert_primitive
from portal.db.tables import mcp_backend, users
from portal.mcp.aggregator import (
    AggregatedPrimitive,
    aggregate_primitives,
    split_namespaced,
)


def test_split_namespaced_first_separator() -> None:
    assert split_namespaced("rag__search") == ("rag", "search")
    # découpe sur le PREMIER __ ; l'original peut en contenir d'autres
    assert split_namespaced("rag__a__b") == ("rag", "a__b")


def test_split_namespaced_invalid() -> None:
    assert split_namespaced("nosep") is None
    assert split_namespaced("__leading") is None


async def _seed(conn: AsyncConnection, *, enabled: bool = True) -> None:
    await conn.execute(
        insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
    )
    await conn.execute(
        insert(mcp_backend).values(
            id="b1", owner_login="alice", namespace="rag", name="RAG",
            url="https://rag/mcp", transport="streamable_http", enabled=enabled,
        )
    )
    await insert_apikey(conn, id="ak1", owner_login="alice", token_hash="h", label="")


async def test_aggregate_namespaces_and_excludes_quarantined(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await set_grant(db_conn, apikey_id="ak1", backend_id="b1", backend_key_id=None)
    await upsert_primitive(
        db_conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "search"}, definition_hash="h1",
    )
    # un tool quarantined doit être exclu
    await upsert_primitive(
        db_conn, backend_id="b1", kind="tool", original_name="evil",
        definition={"name": "evil"}, definition_hash="h2",
    )
    await upsert_primitive(  # redéfinition → quarantaine collante
        db_conn, backend_id="b1", kind="tool", original_name="evil",
        definition={"name": "evil2"}, definition_hash="h2b",
    )

    prims = await aggregate_primitives(
        db_conn, apikey_id="ak1", owner_login="alice", kind="tool"
    )
    names = {p.namespaced_name for p in prims}
    assert names == {"rag__search"}
    assert prims[0] == AggregatedPrimitive(
        namespaced_name="rag__search", kind="tool", backend_id="b1",
        original_name="search", definition={"name": "search"},
    )


async def test_aggregate_allowlist_and_denylist(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    for name in ("a", "b", "c"):
        await upsert_primitive(
            db_conn, backend_id="b1", kind="tool", original_name=name,
            definition={"name": name}, definition_hash=name,
        )

    await set_grant(
        db_conn, apikey_id="ak1", backend_id="b1", backend_key_id=None,
        expose_mode="allowlist", expose=["a", "c"],
    )
    allow = await aggregate_primitives(db_conn, apikey_id="ak1", owner_login="alice", kind="tool")
    assert {p.original_name for p in allow} == {"a", "c"}

    await set_grant(
        db_conn, apikey_id="ak1", backend_id="b1", backend_key_id=None,
        expose_mode="denylist", expose=["b"],
    )
    deny = await aggregate_primitives(db_conn, apikey_id="ak1", owner_login="alice", kind="tool")
    assert {p.original_name for p in deny} == {"a", "c"}


async def test_aggregate_skips_disabled_backend(db_conn: AsyncConnection) -> None:
    await _seed(db_conn, enabled=False)
    await set_grant(db_conn, apikey_id="ak1", backend_id="b1", backend_key_id=None)
    await upsert_primitive(
        db_conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "search"}, definition_hash="h1",
    )
    prims = await aggregate_primitives(db_conn, apikey_id="ak1", owner_login="alice", kind="tool")
    assert prims == []
