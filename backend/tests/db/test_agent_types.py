"""Spec 35 — table agent_type, mcp_profile.exposed_in_workspaces, mcp_apikey.workspace_ref."""

from __future__ import annotations

import uuid

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.agent_types import (
    delete_agent_type,
    get_agent_type,
    insert_agent_type,
    list_agent_types,
    update_agent_type,
)
from portal.db.mcp import insert_apikey, list_apikeys
from portal.db.mcp_profiles import get_profile, insert_profile, set_profile_exposed
from portal.db.tables import mcp_apikey, users


async def _user(conn: AsyncConnection, login: str = "alice") -> None:
    await conn.execute(insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4())))


# ─── agent_type ───────────────────────────────────────────────────────────────


async def test_agent_type_crud(db_conn: AsyncConnection) -> None:
    await insert_agent_type(
        db_conn,
        id="claude",
        label="Claude Code",
        filename=".mcp.json",
        template='{"mcpServers": {}}',
        target_path="{{ project_root }}/.mcp.json",
    )
    row = await get_agent_type(db_conn, "claude")
    assert row is not None
    assert row["label"] == "Claude Code"
    assert row["filename"] == ".mcp.json"
    assert row["enabled"] is True

    assert await update_agent_type(
        db_conn,
        "claude",
        label="Claude",
        filename=".mcp.json",
        template='{"mcpServers": {"x": 1}}',
        target_path="{{ project_root }}/.mcp.json",
        enabled=False,
    )
    row = await get_agent_type(db_conn, "claude")
    assert row is not None
    assert row["label"] == "Claude"
    assert row["enabled"] is False
    assert row["updated_at"] is not None

    assert await delete_agent_type(db_conn, "claude")
    assert await get_agent_type(db_conn, "claude") is None
    assert not await delete_agent_type(db_conn, "claude")


async def test_agent_type_list_ordered(db_conn: AsyncConnection) -> None:
    for aid in ("gemini", "claude"):
        await insert_agent_type(
            db_conn,
            id=aid,
            label=aid,
            filename="f.json",
            template="{}",
            target_path="{{ home }}/f.json",
        )
    rows = await list_agent_types(db_conn)
    assert [r["id"] for r in rows] == ["claude", "gemini"]


async def test_agent_type_list_enabled_only(db_conn: AsyncConnection) -> None:
    await insert_agent_type(
        db_conn,
        id="claude",
        label="Claude",
        filename="f",
        template="{}",
        target_path="/tmp/f",
    )
    await insert_agent_type(
        db_conn,
        id="codex",
        label="Codex",
        filename="f",
        template="{}",
        target_path="/tmp/f",
        enabled=False,
    )
    rows = await list_agent_types(db_conn, enabled_only=True)
    assert [r["id"] for r in rows] == ["claude"]


# ─── mcp_profile.exposed_in_workspaces ────────────────────────────────────────


async def test_profile_exposed_default_false(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await insert_profile(db_conn, id="p1", owner_login="alice", name="défaut")
    row = await get_profile(db_conn, "alice", "p1")
    assert row is not None
    assert row["exposed_in_workspaces"] is False


async def test_set_profile_exposed_scoped_by_owner(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await _user(db_conn, "bob")
    await insert_profile(db_conn, id="p1", owner_login="alice", name="défaut")

    # bob ne peut pas toucher au profil d'alice
    assert not await set_profile_exposed(db_conn, "bob", "p1", exposed=True)

    assert await set_profile_exposed(db_conn, "alice", "p1", exposed=True)
    row = await get_profile(db_conn, "alice", "p1")
    assert row is not None
    assert row["exposed_in_workspaces"] is True


# ─── mcp_apikey.workspace_ref ─────────────────────────────────────────────────


async def test_apikey_workspace_ref(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await insert_apikey(
        db_conn,
        id="k1",
        owner_login="alice",
        token_hash="h" * 64,
        label="ws:alice-api/p1",
        workspace_ref="alice-api",
    )
    row = (
        (await db_conn.execute(select(mcp_apikey).where(mcp_apikey.c.id == "k1")))
        .mappings()
        .first()
    )
    assert row is not None
    assert row["workspace_ref"] == "alice-api"

    # une apikey classique reste sans workspace_ref
    await insert_apikey(db_conn, id="k2", owner_login="alice", token_hash="g" * 64, label="perso")
    rows = {r["id"]: r for r in await list_apikeys(db_conn, "alice")}
    assert rows["k2"]["workspace_ref"] is None
    assert rows["k1"]["workspace_ref"] == "alice-api"
