"""Registre d'instances Termix (spec 18 T2) : CRUD + invariant `is_default` unique.

DB réelle (SAVEPOINT `db_conn`). Skippés sans Docker ; tournent sur Postgres.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db import termix_instance as ti


async def _mk(conn: AsyncConnection, name: str, **over: object) -> dict:
    fields = {
        "name": name,
        "url": f"https://{name}.example.org",
        "apikey_secret": f"termix-{name}",
        **over,
    }
    return await ti.create(conn, **fields)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_create_and_get(db_conn: AsyncConnection) -> None:
    row = await _mk(db_conn, "local", oidc_client_id="termix", is_default=True)
    got = await ti.get(db_conn, row["id"])
    assert got is not None
    assert got["name"] == "local"
    assert got["url"] == "https://local.example.org"
    assert got["apikey_secret"] == "termix-local"
    assert got["oidc_client_id"] == "termix"
    assert got["is_default"] is True


@pytest.mark.asyncio
async def test_name_unique(db_conn: AsyncConnection) -> None:
    await _mk(db_conn, "dup")
    assert await ti.name_exists(db_conn, "dup") is True
    assert await ti.name_exists(db_conn, "autre") is False
    row = await _mk(db_conn, "dup2")
    assert await ti.name_exists(db_conn, "dup2", exclude_id=row["id"]) is False


@pytest.mark.asyncio
async def test_list_ordered_by_name(db_conn: AsyncConnection) -> None:
    await _mk(db_conn, "zeta")
    await _mk(db_conn, "alpha")
    assert [r["name"] for r in await ti.list_all(db_conn)] == ["alpha", "zeta"]


@pytest.mark.asyncio
async def test_single_default_invariant(db_conn: AsyncConnection) -> None:
    a = await _mk(db_conn, "a", is_default=True)
    b = await _mk(db_conn, "b", is_default=True)  # doit décocher a
    rows = {r["name"]: r for r in await ti.list_all(db_conn)}
    assert rows["a"]["is_default"] is False
    assert rows["b"]["is_default"] is True
    default = await ti.get_default(db_conn)
    assert default is not None and default["id"] == b["id"]
    # Repasser a en défaut via update décoche b.
    await ti.update_instance(db_conn, a["id"], is_default=True)
    default = await ti.get_default(db_conn)
    assert default is not None and default["id"] == a["id"]


@pytest.mark.asyncio
async def test_update_and_delete(db_conn: AsyncConnection) -> None:
    row = await _mk(db_conn, "x")
    upd = await ti.update_instance(db_conn, row["id"], url="https://new.example.org", name="x2")
    assert upd is not None and upd["url"] == "https://new.example.org" and upd["name"] == "x2"
    assert await ti.delete_instance(db_conn, row["id"]) is True
    assert await ti.get(db_conn, row["id"]) is None
    assert await ti.delete_instance(db_conn, row["id"]) is False
