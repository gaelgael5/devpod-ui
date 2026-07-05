"""Couche db du registre de services (hub Services & Security)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import insert

from portal.db import user_services as svc
from portal.db.tables import mcp_profile

pytestmark = pytest.mark.asyncio

OWNER = "admin"


async def _mk_profile(db_conn, name: str = "Ops") -> str:
    pid = str(uuid.uuid4())
    await db_conn.execute(
        insert(mcp_profile).values(id=pid, owner_login=OWNER, name=name, description="")
    )
    return pid


async def test_create_and_get(db_conn) -> None:
    pid = await _mk_profile(db_conn)
    sid = await svc.create_service(
        db_conn, owner_login=OWNER, name="Grafana", url="https://g.example", mcp_profile_id=pid
    )
    got = await svc.get_service(db_conn, OWNER, sid)
    assert got is not None
    assert got["name"] == "Grafana"
    assert got["url"] == "https://g.example"
    assert got["mcp_profile_id"] == pid


async def test_list_joins_profile_name(db_conn) -> None:
    pid = await _mk_profile(db_conn, name="Ops")
    await svc.create_service(
        db_conn, owner_login=OWNER, name="Grafana", url="https://g.example", mcp_profile_id=pid
    )
    rows = await svc.list_services(db_conn, OWNER)
    assert len(rows) == 1
    assert rows[0]["mcp_profile_name"] == "Ops"


async def test_list_without_profile(db_conn) -> None:
    await svc.create_service(
        db_conn, owner_login=OWNER, name="Docs", url="https://docs.example", mcp_profile_id=None
    )
    rows = await svc.list_services(db_conn, OWNER)
    assert rows[0]["mcp_profile_name"] is None


async def test_update(db_conn) -> None:
    pid = await _mk_profile(db_conn)
    sid = await svc.create_service(
        db_conn, owner_login=OWNER, name="Old", url="https://old.example", mcp_profile_id=None
    )
    ok = await svc.update_service(
        db_conn, OWNER, sid, name="New", url="https://new.example", mcp_profile_id=pid
    )
    assert ok is True
    got = await svc.get_service(db_conn, OWNER, sid)
    assert got["name"] == "New"
    assert got["mcp_profile_id"] == pid
    assert got["updated_at"] is not None


async def test_update_unknown_returns_false(db_conn) -> None:
    ok = await svc.update_service(
        db_conn, OWNER, "ghost", name="X", url="https://x.example", mcp_profile_id=None
    )
    assert ok is False


async def test_delete(db_conn) -> None:
    sid = await svc.create_service(
        db_conn, owner_login=OWNER, name="Docs", url="https://docs.example", mcp_profile_id=None
    )
    assert await svc.delete_service(db_conn, OWNER, sid) is True
    assert await svc.get_service(db_conn, OWNER, sid) is None
    assert await svc.delete_service(db_conn, OWNER, sid) is False


async def test_owner_scoping(db_conn) -> None:
    sid = await svc.create_service(
        db_conn, owner_login=OWNER, name="Docs", url="https://docs.example", mcp_profile_id=None
    )
    assert await svc.get_service(db_conn, "mallory", sid) is None
    assert (
        await svc.update_service(
            db_conn, "mallory", sid, name="X", url="https://x.example", mcp_profile_id=None
        )
        is False
    )
    assert await svc.delete_service(db_conn, "mallory", sid) is False


async def test_profile_deletion_sets_null_not_cascade(db_conn) -> None:
    """Supprimer le profil MCP ne fait pas disparaître le service (SET NULL)."""
    from sqlalchemy import delete as sa_delete

    pid = await _mk_profile(db_conn)
    sid = await svc.create_service(
        db_conn, owner_login=OWNER, name="Grafana", url="https://g.example", mcp_profile_id=pid
    )
    await db_conn.execute(sa_delete(mcp_profile).where(mcp_profile.c.id == pid))
    got = await svc.get_service(db_conn, OWNER, sid)
    assert got is not None
    assert got["mcp_profile_id"] is None
