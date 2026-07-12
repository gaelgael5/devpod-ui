"""Liens (clé → URL) d'un serveur de test — couche db (table test_host_links)."""
from __future__ import annotations

import pytest

from portal.db.test_hosts import (
    assign_test_host,
    delete_test_host_link,
    list_test_host_links,
    remove_test_host,
    upsert_test_host_link,
)

pytestmark = pytest.mark.asyncio

LOGIN, WS, HOST = "alice", "myapp", "host-test-111-1"


async def _seed_host(conn) -> None:
    await assign_test_host(LOGIN, WS, HOST, "test1", conn)


async def test_upsert_then_list(db_conn) -> None:
    await _seed_host(db_conn)
    assert await upsert_test_host_link(LOGIN, WS, HOST, "app", "http://x:3000", db_conn)
    assert await upsert_test_host_link(LOGIN, WS, HOST, "grafana", "https://g.example", db_conn)
    links = await list_test_host_links(LOGIN, WS, HOST, db_conn)
    assert links == [
        {"key": "app", "url": "http://x:3000"},
        {"key": "grafana", "url": "https://g.example"},
    ]


async def test_upsert_replaces_url_for_same_key(db_conn) -> None:
    await _seed_host(db_conn)
    await upsert_test_host_link(LOGIN, WS, HOST, "app", "http://old", db_conn)
    await upsert_test_host_link(LOGIN, WS, HOST, "app", "http://new", db_conn)
    links = await list_test_host_links(LOGIN, WS, HOST, db_conn)
    assert links == [{"key": "app", "url": "http://new"}]


async def test_delete_link(db_conn) -> None:
    await _seed_host(db_conn)
    await upsert_test_host_link(LOGIN, WS, HOST, "app", "http://x", db_conn)
    assert await delete_test_host_link(LOGIN, WS, HOST, "app", db_conn) is True
    assert await delete_test_host_link(LOGIN, WS, HOST, "app", db_conn) is False
    assert await list_test_host_links(LOGIN, WS, HOST, db_conn) == []


async def test_ownership_guard(db_conn) -> None:
    """Un host qui n'appartient pas au couple (login, workspace) → None/False,
    jamais les liens d'un autre utilisateur."""
    await _seed_host(db_conn)
    await upsert_test_host_link(LOGIN, WS, HOST, "app", "http://x", db_conn)
    assert await list_test_host_links("mallory", WS, HOST, db_conn) is None
    assert await upsert_test_host_link("mallory", WS, HOST, "evil", "http://e", db_conn) is False
    assert await delete_test_host_link("mallory", WS, HOST, "app", db_conn) is False
    assert await list_test_host_links(LOGIN, WS, HOST, db_conn) == [
        {"key": "app", "url": "http://x"}
    ]


async def test_links_cascade_on_host_removal(db_conn) -> None:
    """La destruction de la VM de test emporte ses liens (FK ON DELETE CASCADE)."""
    await _seed_host(db_conn)
    await upsert_test_host_link(LOGIN, WS, HOST, "app", "http://x", db_conn)
    await remove_test_host(HOST, db_conn)
    assert await list_test_host_links(LOGIN, WS, HOST, db_conn) is None

    from sqlalchemy import func, select

    from portal.db.tables import test_host_links

    count = (
        await db_conn.execute(select(func.count()).select_from(test_host_links))
    ).scalar_one()
    assert count == 0
