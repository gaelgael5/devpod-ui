"""Tests de la couche DB recipes (Tour 7)."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.recipes import (
    delete_recipe_db,
    get_recipe_db,
    list_recipes_db,
    load_recipes_as_dict,
    upsert_recipe_db,
)
from portal.recipes.models import RecipeMeta

pytestmark = pytest.mark.asyncio


def _make_meta(rid: str = "node", rtype: str = "install") -> RecipeMeta:
    return RecipeMeta(id=rid, type=rtype, version="1.0.0", description=f"desc-{rid}")


async def _seed_user(conn: AsyncConnection, login: str = "alice") -> None:
    import uuid

    from sqlalchemy import text

    await conn.execute(
        text(
            "INSERT INTO users (login, version, secret_ns) VALUES (:l, '1', :ns)"
            " ON CONFLICT DO NOTHING"
        ),
        {"l": login, "ns": str(uuid.uuid4())},
    )


# ─── upsert + get ─────────────────────────────────────────────────────────────


async def test_upsert_and_get_shared(db_conn: AsyncConnection) -> None:
    meta = _make_meta("node")
    await upsert_recipe_db(meta, "shared", None, db_conn)
    result = await get_recipe_db("node", "shared", None, db_conn)
    assert result is not None
    assert result.id == "node"
    assert result.type == "install"


async def test_get_unknown_returns_none(db_conn: AsyncConnection) -> None:
    result = await get_recipe_db("ghost", "shared", None, db_conn)
    assert result is None


async def test_upsert_updates_existing(db_conn: AsyncConnection) -> None:
    meta1 = _make_meta("node")
    await upsert_recipe_db(meta1, "shared", None, db_conn)
    meta2 = RecipeMeta(id="node", version="2.0.0", description="updated")
    await upsert_recipe_db(meta2, "shared", None, db_conn)
    result = await get_recipe_db("node", "shared", None, db_conn)
    assert result is not None
    assert result.version == "2.0.0"
    assert result.description == "updated"


# ─── list ─────────────────────────────────────────────────────────────────────


async def test_list_empty(db_conn: AsyncConnection) -> None:
    results = await list_recipes_db("alice", db_conn)
    assert results == []


async def test_list_shared_visible_to_all(db_conn: AsyncConnection) -> None:
    await upsert_recipe_db(_make_meta("node"), "shared", None, db_conn)
    await upsert_recipe_db(_make_meta("python"), "shared", None, db_conn)

    results = await list_recipes_db("alice", db_conn)
    ids = {m.id for _, m in results}
    assert {"node", "python"} == ids


async def test_list_user_recipe_isolated(db_conn: AsyncConnection) -> None:
    await _seed_user(db_conn, "alice")
    await _seed_user(db_conn, "bob")
    await upsert_recipe_db(_make_meta("my-start", "start"), "user", "alice", db_conn)

    alice_ids = {m.id for _, m in await list_recipes_db("alice", db_conn)}
    bob_ids = {m.id for _, m in await list_recipes_db("bob", db_conn)}

    assert "my-start" in alice_ids
    assert "my-start" not in bob_ids


async def test_list_scope_filter(db_conn: AsyncConnection) -> None:
    await upsert_recipe_db(_make_meta("node"), "shared", None, db_conn)
    await upsert_recipe_db(_make_meta("builtin-r"), "builtin", None, db_conn)

    shared_only = await list_recipes_db("alice", db_conn, scope_filter="shared")
    assert all(s == "shared" for s, _ in shared_only)
    assert len(shared_only) == 1


# ─── load_recipes_as_dict ─────────────────────────────────────────────────────


async def test_load_as_dict_type_filter(db_conn: AsyncConnection) -> None:
    await upsert_recipe_db(_make_meta("node", "install"), "shared", None, db_conn)
    await upsert_recipe_db(_make_meta("launcher", "start"), "shared", None, db_conn)

    installs = await load_recipes_as_dict("alice", db_conn, type_filter="install")
    starts = await load_recipes_as_dict("alice", db_conn, type_filter="start")

    assert "node" in installs
    assert "launcher" not in installs
    assert "launcher" in starts
    assert "node" not in starts


async def test_load_as_dict_no_filter(db_conn: AsyncConnection) -> None:
    await upsert_recipe_db(_make_meta("node", "install"), "shared", None, db_conn)
    await upsert_recipe_db(_make_meta("launcher", "start"), "shared", None, db_conn)

    all_recipes = await load_recipes_as_dict("alice", db_conn)
    assert {"node", "launcher"} == set(all_recipes)


# ─── delete ───────────────────────────────────────────────────────────────────


async def test_delete_shared(db_conn: AsyncConnection) -> None:
    await upsert_recipe_db(_make_meta("node"), "shared", None, db_conn)
    deleted = await delete_recipe_db("node", "shared", None, db_conn)
    assert deleted is True
    assert await get_recipe_db("node", "shared", None, db_conn) is None


async def test_delete_nonexistent_returns_false(db_conn: AsyncConnection) -> None:
    deleted = await delete_recipe_db("ghost", "shared", None, db_conn)
    assert deleted is False


async def test_delete_user_recipe(db_conn: AsyncConnection) -> None:
    await _seed_user(db_conn, "alice")
    await upsert_recipe_db(_make_meta("my-start", "start"), "user", "alice", db_conn)
    deleted = await delete_recipe_db("my-start", "user", "alice", db_conn)
    assert deleted is True


async def test_shared_and_user_same_id_independent(db_conn: AsyncConnection) -> None:
    """Un recipe user peut avoir le même id qu'un shared sans conflit."""
    await _seed_user(db_conn, "alice")
    shared = _make_meta("node")
    user = RecipeMeta(id="node", version="2.0.0", description="user-override", type="install")
    await upsert_recipe_db(shared, "shared", None, db_conn)
    await upsert_recipe_db(user, "user", "alice", db_conn)

    shared_r = await get_recipe_db("node", "shared", None, db_conn)
    user_r = await get_recipe_db("node", "user", "alice", db_conn)
    assert shared_r is not None and shared_r.version == "1.0.0"
    assert user_r is not None and user_r.version == "2.0.0"
