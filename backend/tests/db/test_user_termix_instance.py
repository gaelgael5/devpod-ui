"""Rattachement user→instance Termix (spec 18 T4) : list/set + résolution.

DB réelle (SAVEPOINT `db_conn`). Skippés sans Docker ; tournent sur Postgres.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db import termix_instance as ti
from portal.db.tables import users
from portal.db.user_config import list_users_db, set_user_termix_instance_db


async def _mk_user(conn: AsyncConnection, login: str) -> None:
    await conn.execute(users.insert().values(login=login, version="1", secret_ns=str(uuid.uuid4())))


async def _mk_instance(conn: AsyncConnection, name: str, **over: object) -> dict:
    return await ti.create(
        conn, name=name, url=f"https://{name}", apikey_secret=f"s-{name}", **over
    )  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_list_and_set(db_conn: AsyncConnection) -> None:
    await _mk_user(db_conn, "alice")
    inst = await _mk_instance(db_conn, "prod")
    assert await set_user_termix_instance_db("alice", inst["id"], db_conn) is True
    assert await set_user_termix_instance_db("ghost", inst["id"], db_conn) is False
    rows = {r["login"]: r for r in await list_users_db(db_conn)}
    assert rows["alice"]["termix_instance_id"] == inst["id"]


@pytest.mark.asyncio
async def test_resolve_explicit_else_default(db_conn: AsyncConnection) -> None:
    await _mk_user(db_conn, "bob")
    default = await _mk_instance(db_conn, "local", is_default=True)
    prod = await _mk_instance(db_conn, "prod")

    # Sans assignation → défaut.
    r = await ti.resolve_for_user(db_conn, "bob")
    assert r is not None and r["id"] == default["id"]

    # Assignation explicite → cette instance.
    await set_user_termix_instance_db("bob", prod["id"], db_conn)
    r = await ti.resolve_for_user(db_conn, "bob")
    assert r is not None and r["id"] == prod["id"]

    # Retour à None → héritage défaut.
    await set_user_termix_instance_db("bob", None, db_conn)
    r = await ti.resolve_for_user(db_conn, "bob")
    assert r is not None and r["id"] == default["id"]


@pytest.mark.asyncio
async def test_set_null_on_instance_delete(db_conn: AsyncConnection) -> None:
    await _mk_user(db_conn, "carol")
    prod = await _mk_instance(db_conn, "prod")
    await set_user_termix_instance_db("carol", prod["id"], db_conn)
    await ti.delete_instance(db_conn, prod["id"])  # FK SET NULL
    rows = {r["login"]: r for r in await list_users_db(db_conn)}
    assert rows["carol"]["termix_instance_id"] is None
