"""Tests de la persistance du kiosque d'applications global (kiosk_applications)."""
from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from portal.db.kiosk_applications import (
    add_application,
    delete_application,
    list_applications,
    update_application,
)


@pytest.mark.asyncio
async def test_list_empty(db_conn):
    assert await list_applications(db_conn) == []


@pytest.mark.asyncio
async def test_add_and_list_ordered(db_conn):
    a = await add_application("Doc", "https://doc.yoops.org", "📚", db_conn)
    b = await add_application("Rag", "https://rag.yoops.org", "", db_conn)
    assert a["position"] == 1
    assert b["position"] == 2
    apps = await list_applications(db_conn)
    assert [x["name"] for x in apps] == ["Doc", "Rag"]
    assert apps[0]["icon"] == "📚"


@pytest.mark.asyncio
async def test_duplicate_name_raises(db_conn):
    await add_application("Doc", "https://doc.yoops.org", "", db_conn)
    with pytest.raises(IntegrityError):
        await add_application("Doc", "https://autre.io", "", db_conn)


@pytest.mark.asyncio
async def test_update(db_conn):
    row = await add_application("Doc", "https://doc.yoops.org", "", db_conn)
    updated = await update_application(
        row["id"], "Docs", "https://doc.yoops.org/ui", "📚", db_conn
    )
    assert updated is not None
    assert updated["name"] == "Docs"
    assert updated["url"] == "https://doc.yoops.org/ui"
    assert updated["icon"] == "📚"
    assert updated["position"] == row["position"]  # la position ne bouge pas


@pytest.mark.asyncio
async def test_update_unknown_returns_none(db_conn):
    assert await update_application(999, "X", "https://x.io", "", db_conn) is None


@pytest.mark.asyncio
async def test_update_name_collision_raises(db_conn):
    await add_application("Doc", "https://doc.yoops.org", "", db_conn)
    row = await add_application("Rag", "https://rag.yoops.org", "", db_conn)
    with pytest.raises(IntegrityError):
        await update_application(row["id"], "Doc", "https://rag.yoops.org", "", db_conn)


@pytest.mark.asyncio
async def test_delete(db_conn):
    row = await add_application("Doc", "https://doc.yoops.org", "", db_conn)
    assert await delete_application(row["id"], db_conn) is True
    assert await list_applications(db_conn) == []
    assert await delete_application(row["id"], db_conn) is False
