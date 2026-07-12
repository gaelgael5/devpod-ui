from __future__ import annotations

import uuid

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import (
    delete_apikey,
    delete_backend,
    delete_backend_key,
    find_apikey_by_hash,
    get_apikey,
    get_backend,
    get_backend_key,
    get_backend_key_secret,
    insert_apikey,
    insert_backend,
    insert_backend_key,
    list_apikeys,
    list_backend_keys,
    list_backends,
    revoke_apikey,
    set_apikey_profile,
    update_backend,
)
from portal.db.mcp_profiles import (
    delete_profile,
    delete_profile_entry,
    find_first_backend_key,
    get_profile,
    insert_profile,
    list_entries_for_apikey,
    list_profile_entries,
    list_profiles,
    update_profile,
    upsert_profile_entry,
)
from portal.db.tables import (
    mcp_apikey,
    mcp_backend,
    mcp_backend_key,
    mcp_profile,
    mcp_profile_entry,
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
        insert(mcp_profile).values(id="p1", owner_login="alice", name="défaut")
    )
    await db_conn.execute(
        insert(mcp_profile_entry).values(
            profile_id="p1", backend_id="b1", backend_key_id="k1"
        )
    )
    await db_conn.execute(
        insert(mcp_apikey).values(
            id="a1", owner_login="alice", token_hash="h", label="cli", profile_id="p1"
        )
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


async def test_delete_backend_key_nullifies_profile_entries(db_conn: AsyncConnection) -> None:
    """Suppression d'une backend_key → l'entry survit avec backend_key_id NULL (SET NULL).

    Contrairement aux anciens grants (CASCADE), une entry de profil n'est pas
    supprimée : backend_key_id passe à NULL, ce qui bascule le backend en
    auto-résolution (première clé enabled).
    """
    await _user(db_conn)
    await insert_backend(
        db_conn, id="b1", owner_login="alice", namespace="rag",
        name="RAG", url="https://rag/mcp", transport="streamable_http",
    )
    await insert_backend_key(
        db_conn, id="k1", backend_id="b1", slug="read", description="",
        storage_type="local", secret_value_local=b"x",
        secret_value_vault_ref=None, vault_identifier=None,
    )
    await insert_profile(db_conn, id="p1", owner_login="alice", name="défaut")
    await upsert_profile_entry(
        db_conn, profile_id="p1", backend_id="b1", backend_key_id="k1", tools=None
    )

    entries_before = await list_profile_entries(db_conn, "p1")
    assert len(entries_before) == 1 and entries_before[0]["backend_key_id"] == "k1"

    await delete_backend_key(db_conn, "b1", "k1")

    entries_after = await list_profile_entries(db_conn, "p1")
    assert len(entries_after) == 1, "l'entry doit survivre à la suppression de la clé"
    assert entries_after[0]["backend_key_id"] is None, "backend_key_id doit passer à NULL"


async def test_apikey_lifecycle_and_profile_entries(db_conn: AsyncConnection) -> None:
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
    assert rows[0]["profile_id"] is None  # aucun profil par défaut

    found = await find_apikey_by_hash(db_conn, "HASH")
    assert found is not None and found["id"] == "a1" and found["owner_login"] == "alice"
    assert "token_hash" not in found

    # Pas de profil associé → deny-by-default : aucune entry visible
    assert await list_entries_for_apikey(db_conn, apikey_id="a1", owner_login="alice") == []

    await insert_profile(db_conn, id="p1", owner_login="alice", name="défaut")
    await upsert_profile_entry(
        db_conn, profile_id="p1", backend_id="b1", backend_key_id="k1", tools=None
    )
    # upsert : re-set sur le même (profile, backend) remplace la clé sans doublon
    await upsert_profile_entry(
        db_conn, profile_id="p1", backend_id="b1", backend_key_id="k1", tools=None
    )
    entries = await list_profile_entries(db_conn, "p1")
    assert len(entries) == 1 and entries[0]["backend_key_id"] == "k1"

    # Association apikey → profil, puis lecture des entries via l'apikey
    assert await set_apikey_profile(db_conn, "alice", "a1", "p1") is True
    via_key = await list_entries_for_apikey(db_conn, apikey_id="a1", owner_login="alice")
    assert len(via_key) == 1 and via_key[0]["backend_id"] == "b1"
    # isolation : bob ne peut pas lire les entries via l'apikey d'alice
    assert await list_entries_for_apikey(db_conn, apikey_id="a1", owner_login="bob") == []

    assert await delete_profile_entry(db_conn, "p1", "b1") is True
    assert await list_entries_for_apikey(db_conn, apikey_id="a1", owner_login="alice") == []

    assert await revoke_apikey(db_conn, "alice", "a1") is True
    assert await find_apikey_by_hash(db_conn, "HASH") is None
    assert await delete_apikey(db_conn, "alice", "a1") is True


async def test_profile_crud_scoped_to_owner(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await _user(db_conn, "bob")
    await insert_profile(db_conn, id="p1", owner_login="alice", name="défaut", description="d")

    rows = await list_profiles(db_conn, "alice")
    assert len(rows) == 1 and rows[0]["name"] == "défaut"

    got = await get_profile(db_conn, "alice", "p1")
    assert got is not None and got["description"] == "d"

    # isolation : bob ne voit pas le profil d'alice
    assert await get_profile(db_conn, "bob", "p1") is None
    assert await list_profiles(db_conn, "bob") == []
    assert await update_profile(db_conn, "bob", "p1", name="pwn", description="") is False
    assert await delete_profile(db_conn, "bob", "p1") is False

    assert await update_profile(db_conn, "alice", "p1", name="perso", description="dd") is True
    got = await get_profile(db_conn, "alice", "p1")
    assert got["name"] == "perso" and got["description"] == "dd"

    assert await delete_profile(db_conn, "alice", "p1") is True
    assert await get_profile(db_conn, "alice", "p1") is None


async def test_delete_profile_cascades_entries_and_detaches_apikey(
    db_conn: AsyncConnection,
) -> None:
    """Suppression d'un profil → entries en CASCADE, apikey.profile_id → NULL."""
    await _user(db_conn)
    await insert_backend(
        db_conn, id="b1", owner_login="alice", namespace="rag",
        name="RAG", url="https://rag/mcp", transport="streamable_http",
    )
    await insert_profile(db_conn, id="p1", owner_login="alice", name="défaut")
    await upsert_profile_entry(
        db_conn, profile_id="p1", backend_id="b1", backend_key_id=None, tools=None
    )
    await insert_apikey(
        db_conn, id="a1", owner_login="alice", token_hash="H", label="cli", profile_id="p1"
    )

    assert await delete_profile(db_conn, "alice", "p1") is True
    assert await list_profile_entries(db_conn, "p1") == []
    got = await get_apikey(db_conn, "alice", "a1")
    assert got is not None and got["profile_id"] is None  # deny-by-default après détachement


async def test_get_apikey_scoped_to_owner(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await _user(db_conn, "bob")
    await insert_apikey(db_conn, id="a1", owner_login="alice", token_hash="H", label="cli")

    got = await get_apikey(db_conn, "alice", "a1")
    assert got is not None and got["id"] == "a1"
    assert "token_hash" not in got  # jamais exposé

    # isolation : bob ne voit pas l'apikey d'alice ; id inconnu → None
    assert await get_apikey(db_conn, "bob", "a1") is None
    assert await get_apikey(db_conn, "alice", "absent") is None


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


async def test_get_backend_key_secret_returns_blob(db_conn: AsyncConnection) -> None:
    await _seed_backend(db_conn)
    await insert_backend_key(
        db_conn,
        id="k1", backend_id="b1", slug="prod", description="",
        storage_type="local", secret_value_local=b"\x01\x02\x03",
        secret_value_vault_ref=None, vault_identifier=None,
    )

    row = await get_backend_key_secret(db_conn, "b1", "k1")
    assert row is not None
    assert row["storage_type"] == "local"
    assert row["secret_value_local"] == b"\x01\x02\x03"
    assert row["secret_value_vault_ref"] is None

    # Hygiène : le listing NE doit PAS exposer le blob.
    listed = await get_backend_key(db_conn, "b1", "k1")
    assert listed is not None
    assert "secret_value_local" not in listed


async def test_get_backend_key_secret_unknown_returns_none(db_conn: AsyncConnection) -> None:
    await _seed_backend(db_conn)
    assert await get_backend_key_secret(db_conn, "b1", "nope") is None


async def test_find_first_backend_key_skips_disabled(db_conn: AsyncConnection) -> None:
    """Auto-résolution (backend_key_id NULL) : seule une clé enabled est candidate."""
    await _seed_backend(db_conn)
    # Aucune clé → None
    assert await find_first_backend_key(db_conn, "b1") is None

    await insert_backend_key(
        db_conn, id="k1", backend_id="b1", slug="off", description="",
        storage_type="local", secret_value_local=b"a",
        secret_value_vault_ref=None, vault_identifier=None,
    )
    await db_conn.execute(
        mcp_backend_key.update()
        .where(mcp_backend_key.c.id == "k1")
        .values(enabled=False)
    )
    # Seule clé désactivée → None
    assert await find_first_backend_key(db_conn, "b1") is None

    await insert_backend_key(
        db_conn, id="k2", backend_id="b1", slug="on", description="",
        storage_type="local", secret_value_local=b"b",
        secret_value_vault_ref=None, vault_identifier=None,
    )
    row = await find_first_backend_key(db_conn, "b1")
    assert row is not None and row["id"] == "k2"
    assert row["secret_value_local"] == b"b"


# ---------------------------------------------------------------------------
# list_all_enabled_backends
# ---------------------------------------------------------------------------


async def test_list_all_enabled_backends(db_conn: AsyncConnection) -> None:
    from portal.db.mcp import list_all_enabled_backends

    await db_conn.execute(
        insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
    )
    await db_conn.execute(insert(mcp_backend).values(
        id="b1", owner_login="alice", namespace="rag", name="RAG",
        url="https://rag/mcp", transport="streamable_http", enabled=True))
    await db_conn.execute(insert(mcp_backend).values(
        id="b2", owner_login="alice", namespace="docs", name="Docs",
        url="https://docs/mcp", transport="streamable_http", enabled=False))
    rows = await list_all_enabled_backends(db_conn)
    ids = {r["id"] for r in rows}
    assert ids == {"b1"}  # b2 disabled exclu
