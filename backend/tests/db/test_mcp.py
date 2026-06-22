from __future__ import annotations

import uuid

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import (
    delete_apikey,
    delete_backend,
    delete_backend_key,
    delete_grant,
    find_apikey_by_hash,
    get_backend,
    get_backend_key,
    insert_apikey,
    insert_backend,
    insert_backend_key,
    list_apikeys,
    list_backend_keys,
    list_backends,
    list_grants,
    revoke_apikey,
    set_grant,
    update_backend,
)
from portal.db.tables import (
    mcp_apikey,
    mcp_apikey_grant,
    mcp_backend,
    mcp_backend_key,
    users,
)


async def _user(conn: AsyncConnection, login: str = "alice") -> None:
    await conn.execute(
        insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4()))
    )


async def test_tables_smoke(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await db_conn.execute(
        insert(mcp_backend).values(
            id="b1",
            owner_login="alice",
            namespace="rag",
            name="RAG",
            url="https://rag.yoops.org/mcp",
            transport="streamable_http",
        )
    )
    await db_conn.execute(
        insert(mcp_backend_key).values(
            id="k1",
            backend_id="b1",
            slug="read",
            description="lecture seule",
            storage_type="local",
            secret_value_local=b"\x00" * 16,
        )
    )
    await db_conn.execute(
        insert(mcp_apikey).values(id="a1", owner_login="alice", token_hash="h", label="cli")
    )
    await db_conn.execute(
        insert(mcp_apikey_grant).values(apikey_id="a1", backend_id="b1", backend_key_id="k1")
    )
    rows = (await db_conn.execute(select(mcp_backend.c.namespace))).all()
    assert rows == [("rag",)]


async def test_backend_crud(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await insert_backend(
        db_conn, id="b1", owner_login="alice", namespace="rag",
        name="RAG", url="https://rag/mcp", transport="streamable_http",
    )
    rows = await list_backends(db_conn, "alice")
    assert len(rows) == 1 and rows[0]["namespace"] == "rag"
    assert "owner_login" in rows[0]

    got = await get_backend(db_conn, "alice", "b1")
    assert got is not None and got["name"] == "RAG"

    # isolation : bob ne voit rien
    await _user(db_conn, "bob")
    assert await get_backend(db_conn, "bob", "b1") is None
    assert await list_backends(db_conn, "bob") == []

    ok = await update_backend(
        db_conn, "alice", "b1", name="RAG2", url="https://rag2/mcp",
        transport="sse", enabled=False,
    )
    assert ok is True
    got = await get_backend(db_conn, "alice", "b1")
    assert got["name"] == "RAG2" and got["enabled"] is False

    assert await delete_backend(db_conn, "alice", "b1") is True
    assert await get_backend(db_conn, "alice", "b1") is None


async def test_backend_key_never_exposes_local_value(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await insert_backend(
        db_conn, id="b1", owner_login="alice", namespace="rag",
        name="RAG", url="https://rag/mcp", transport="streamable_http",
    )
    await insert_backend_key(
        db_conn, id="k1", backend_id="b1", slug="read", description="ro",
        storage_type="local", secret_value_local=b"\xDE\xAD" * 8,
        secret_value_vault_ref=None, vault_identifier=None,
    )
    rows = await list_backend_keys(db_conn, "b1")
    assert len(rows) == 1 and rows[0]["slug"] == "read"
    assert "secret_value_local" not in rows[0]
    got = await get_backend_key(db_conn, "b1", "k1")
    assert got is not None and "secret_value_local" not in got
    assert await delete_backend_key(db_conn, "b1", "k1") is True


async def test_apikey_lifecycle_and_grants(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await insert_backend(
        db_conn, id="b1", owner_login="alice", namespace="rag",
        name="RAG", url="https://rag/mcp", transport="streamable_http",
    )
    await insert_backend_key(
        db_conn, id="k1", backend_id="b1", slug="read", description="",
        storage_type="local", secret_value_local=b"x", secret_value_vault_ref=None,
        vault_identifier=None,
    )
    await insert_apikey(db_conn, id="a1", owner_login="alice", token_hash="HASH", label="cli")

    rows = await list_apikeys(db_conn, "alice")
    assert len(rows) == 1 and "token_hash" not in rows[0]

    found = await find_apikey_by_hash(db_conn, "HASH")
    assert found is not None and found["id"] == "a1" and found["owner_login"] == "alice"
    assert "token_hash" not in found

    await set_grant(db_conn, apikey_id="a1", backend_id="b1", backend_key_id="k1")
    # upsert : re-set sur le même (apikey, backend) remplace la clé sans doublon
    await set_grant(db_conn, apikey_id="a1", backend_id="b1", backend_key_id="k1")
    grants = await list_grants(db_conn, "a1")
    assert len(grants) == 1 and grants[0]["backend_key_id"] == "k1"

    assert await delete_grant(db_conn, "a1", "b1") is True
    assert await list_grants(db_conn, "a1") == []

    assert await revoke_apikey(db_conn, "alice", "a1") is True
    assert await find_apikey_by_hash(db_conn, "HASH") is None
    assert await delete_apikey(db_conn, "alice", "a1") is True
