from __future__ import annotations

import uuid

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp_catalog import list_primitives, set_quarantine, upsert_primitive
from portal.db.mcp_profiles import list_profile_entries, upsert_profile_entry
from portal.db.tables import (
    mcp_audit_log,
    mcp_backend,
    mcp_profile,
    mcp_tool_catalog,
    users,
)


async def _seed_backend(conn: AsyncConnection) -> None:
    await conn.execute(
        insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
    )
    await conn.execute(
        insert(mcp_backend).values(
            id="b1", owner_login="alice", namespace="rag", name="RAG",
            url="https://rag/mcp", transport="streamable_http",
        )
    )


async def test_catalog_and_audit_smoke(db_conn: AsyncConnection) -> None:
    await _seed_backend(db_conn)
    await db_conn.execute(
        insert(mcp_tool_catalog).values(
            backend_id="b1", kind="tool", original_name="search",
            definition={"name": "search"}, definition_hash="h",
        )
    )
    await db_conn.execute(
        insert(mcp_audit_log).values(status="ok", owner_login="alice", backend_id="b1")
    )
    rows = (await db_conn.execute(select(mcp_tool_catalog.c.original_name))).all()
    assert rows == [("search",)]


async def test_upsert_detects_rugpull(db_conn: AsyncConnection) -> None:
    await _seed_backend(db_conn)
    q1 = await upsert_primitive(
        db_conn,
        backend_id="b1",
        kind="tool",
        original_name="search",
        definition={"name": "search", "v": 1},
        definition_hash="h1",
    )
    assert q1 is False  # première insertion, pas de quarantaine
    # Redéfinition (hash différent) → quarantaine collante
    q2 = await upsert_primitive(
        db_conn,
        backend_id="b1",
        kind="tool",
        original_name="search",
        definition={"name": "search", "v": 2},
        definition_hash="h2",
    )
    assert q2 is True
    rows = await list_primitives(db_conn, "b1", "tool")
    assert rows[0]["quarantined"] is True
    await set_quarantine(db_conn, "b1", "tool", "search", False)
    rows = await list_primitives(db_conn, "b1", "tool")
    assert rows[0]["quarantined"] is False


async def test_profile_entry_curation_defaults(db_conn: AsyncConnection) -> None:
    """Curation par défaut d'une entry de profil : tools NULL = tous les tools.

    Remplace l'ancien test sur mcp_apikey_grant (expose_mode='all' / expose=[]) :
    la curation vit désormais sur mcp_profile_entry.tools
    (null = tout, [] = rien, [...] = subset explicite).
    """
    await _seed_backend(db_conn)
    await db_conn.execute(
        insert(mcp_profile).values(id="p1", owner_login="alice", name="défaut")
    )
    await upsert_profile_entry(
        db_conn, profile_id="p1", backend_id="b1", backend_key_id=None, tools=None
    )
    entries = await list_profile_entries(db_conn, "p1")
    assert len(entries) == 1
    assert entries[0]["tools"] is None  # NULL = tous les tools exposés
    assert entries[0]["backend_key_id"] is None  # backend public sans clé

    # Curation explicite : subset, puis liste vide (= aucun tool)
    await upsert_profile_entry(
        db_conn, profile_id="p1", backend_id="b1", backend_key_id=None, tools=["search"]
    )
    entries = await list_profile_entries(db_conn, "p1")
    assert entries[0]["tools"] == ["search"]

    await upsert_profile_entry(
        db_conn, profile_id="p1", backend_id="b1", backend_key_id=None, tools=[]
    )
    entries = await list_profile_entries(db_conn, "p1")
    assert entries[0]["tools"] == []
