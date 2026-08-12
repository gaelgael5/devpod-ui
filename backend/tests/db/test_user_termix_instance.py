"""Rattachement user→instances Termix N-N ≤3 (spec 18 T4b) : set + résolution.

DB réelle (SAVEPOINT `db_conn`). Skippés sans Docker ; tournent sur Postgres.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db import termix_instance as ti
from portal.db import user_termix_instance as uti
from portal.db.tables import users
from portal.db.user_config import list_users_db


async def _mk_user(conn: AsyncConnection, login: str) -> None:
    await conn.execute(
        users.insert().values(login=login, version="1", secret_ns=str(uuid.uuid4()))
    )


async def _mk_instance(conn: AsyncConnection, name: str, **over: object) -> dict:
    return await ti.create(
        conn, name=name, url=f"https://{name}", apikey_secret=f"s-{name}", **over
    )  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_set_and_list(db_conn: AsyncConnection) -> None:
    await _mk_user(db_conn, "alice")
    a = await _mk_instance(db_conn, "a")
    b = await _mk_instance(db_conn, "b")
    c = await _mk_instance(db_conn, "c")
    await uti.set_instances_for_user(db_conn, "alice", [a["id"], b["id"], c["id"]])
    assert await uti.list_instance_ids(db_conn, "alice") == sorted([a["id"], b["id"], c["id"]])
    # Remplacement : retire c, garde a/b.
    await uti.set_instances_for_user(db_conn, "alice", [a["id"], b["id"]])
    assert await uti.list_instance_ids(db_conn, "alice") == sorted([a["id"], b["id"]])
    # list_users_db agrège les ids.
    rows = {r["login"]: r for r in await list_users_db(db_conn)}
    assert sorted(rows["alice"]["termix_instance_ids"]) == sorted([a["id"], b["id"]])


@pytest.mark.asyncio
async def test_resolve_explicit_else_default(db_conn: AsyncConnection) -> None:
    await _mk_user(db_conn, "bob")
    default = await _mk_instance(db_conn, "local", is_default=True)
    p1 = await _mk_instance(db_conn, "p1")
    p2 = await _mk_instance(db_conn, "p2")

    # Sans rattachement → [défaut].
    r = await uti.resolve_instances_for_user(db_conn, "bob")
    assert [i["id"] for i in r] == [default["id"]]

    # Rattachements explicites → ces instances (pas le défaut).
    await uti.set_instances_for_user(db_conn, "bob", [p1["id"], p2["id"]])
    r = await uti.resolve_instances_for_user(db_conn, "bob")
    assert sorted(i["id"] for i in r) == sorted([p1["id"], p2["id"]])


@pytest.mark.asyncio
async def test_cascade_on_instance_delete(db_conn: AsyncConnection) -> None:
    await _mk_user(db_conn, "carol")
    p = await _mk_instance(db_conn, "p")
    await uti.set_instances_for_user(db_conn, "carol", [p["id"]])
    await ti.delete_instance(db_conn, p["id"])  # CASCADE
    assert await uti.list_instance_ids(db_conn, "carol") == []
