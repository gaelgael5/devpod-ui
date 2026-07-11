"""Couche db des préférences utilisateur (table user_preferences)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import insert

from portal.db.tables import users
from portal.db.user_preferences import list_preferences, upsert_preference

pytestmark = pytest.mark.asyncio


async def _user(conn, login: str = "alice") -> str:
    await conn.execute(insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4())))
    return login


async def test_upsert_and_list_roundtrip_typed(db_conn) -> None:
    login = await _user(db_conn)
    await upsert_preference(login, "flag", True, db_conn)
    await upsert_preference(login, "count", 7, db_conn)
    await upsert_preference(login, "label", "hello", db_conn)

    prefs = await list_preferences(login, db_conn)
    assert prefs == {"flag": True, "count": 7, "label": "hello"}
    # Les types sont bien préservés (bool n'est pas relu comme int).
    assert isinstance(prefs["flag"], bool)
    assert isinstance(prefs["count"], int) and not isinstance(prefs["count"], bool)


async def test_upsert_overwrites_same_key(db_conn) -> None:
    login = await _user(db_conn)
    await upsert_preference(login, "k", True, db_conn)
    await upsert_preference(login, "k", False, db_conn)
    # Changement de type sur la même clé : la valeur ET le type suivent.
    await upsert_preference(login, "k", "now-a-string", db_conn)

    prefs = await list_preferences(login, db_conn)
    assert prefs == {"k": "now-a-string"}


async def test_false_and_zero_are_preserved(db_conn) -> None:
    login = await _user(db_conn)
    await upsert_preference(login, "collapsed", False, db_conn)
    await upsert_preference(login, "zero", 0, db_conn)

    prefs = await list_preferences(login, db_conn)
    assert prefs["collapsed"] is False  # pas confondu avec « absent »
    assert prefs["zero"] == 0


async def test_isolated_per_user(db_conn) -> None:
    await _user(db_conn, "alice")
    await _user(db_conn, "bob")
    await upsert_preference("alice", "x", 1, db_conn)
    await upsert_preference("bob", "x", 2, db_conn)

    assert await list_preferences("alice", db_conn) == {"x": 1}
    assert await list_preferences("bob", db_conn) == {"x": 2}
