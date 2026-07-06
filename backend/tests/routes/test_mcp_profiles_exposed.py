"""Spec 35 §8.6 — route PUT /me/mcp/profiles/{id}/exposed (fail closed au décochage)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.agents.keys import rotate_workspace_keys
from portal.db.mcp import find_apikey_by_hash
from portal.db.mcp_profiles import get_profile, insert_profile, set_profile_exposed
from portal.db.tables import users
from portal.mcp.service import token_hash

_RESYNC_CALLS: list[tuple[str, set[str] | None]] = []


@pytest.fixture(autouse=True)
def _capture_resync(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, set[str] | None]]:
    """Capture les resyncs planifiés (le vrai resync ouvrirait une seconde
    connexion sur un pool de 1 → deadlock en test)."""
    import portal.routes.mcp_profiles as mod

    _RESYNC_CALLS.clear()

    async def fake_resync(login: str, only: set[str] | None = None) -> dict[str, list[str]]:
        _RESYNC_CALLS.append((login, only))
        return {"synced": [], "skipped": [], "failed": []}

    monkeypatch.setattr(mod, "resync_owner_workspaces", fake_resync)
    return _RESYNC_CALLS


@pytest.fixture
async def client(db_conn: AsyncConnection) -> AsyncGenerator[AsyncClient, None]:
    from fastapi import FastAPI

    from portal.auth.rbac import UserInfo, require_user
    from portal.db.engine import get_conn
    from portal.routes.mcp_profiles import router

    await db_conn.execute(
        insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
    )
    app = FastAPI()
    app.include_router(router, prefix="/me")
    app.dependency_overrides[require_user] = lambda: UserInfo(login="alice", roles=["dev"])
    app.dependency_overrides[get_conn] = lambda: db_conn
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_expose_profile_sets_flag_and_schedules_full_resync(
    client: AsyncClient, db_conn: AsyncConnection
) -> None:
    await insert_profile(db_conn, id="p1", owner_login="alice", name="défaut")

    r = await client.put("/me/mcp/profiles/p1/exposed", json={"exposed": True})
    assert r.status_code == 200
    assert r.json() == {"id": "p1", "exposed": True, "affected_workspaces": []}
    row = await get_profile(db_conn, "alice", "p1")
    assert row is not None and row["exposed_in_workspaces"] is True
    assert _RESYNC_CALLS == [("alice", None)]


async def test_unexpose_revokes_keys_fail_closed(
    client: AsyncClient, db_conn: AsyncConnection
) -> None:
    await insert_profile(db_conn, id="p1", owner_login="alice", name="défaut")
    await set_profile_exposed(db_conn, "alice", "p1", exposed=True)
    keys = await rotate_workspace_keys(db_conn, "alice", "alice-api")
    assert len(keys) == 1

    r = await client.put("/me/mcp/profiles/p1/exposed", json={"exposed": False})
    assert r.status_code == 200
    body = r.json()
    assert body["exposed"] is False
    assert body["affected_workspaces"] == ["alice-api"]
    # clef révoquée dans la même transaction (fail closed)
    assert await find_apikey_by_hash(db_conn, token_hash(keys[0].token)) is None
    # resync ciblé sur les workspaces affectés
    assert [("alice", {"alice-api"})] == _RESYNC_CALLS


async def test_unexpose_without_keys_schedules_nothing(
    client: AsyncClient, db_conn: AsyncConnection
) -> None:
    await insert_profile(db_conn, id="p1", owner_login="alice", name="défaut")
    r = await client.put("/me/mcp/profiles/p1/exposed", json={"exposed": False})
    assert r.status_code == 200
    assert _RESYNC_CALLS == []


async def test_exposed_unknown_profile_404(client: AsyncClient) -> None:
    r = await client.put("/me/mcp/profiles/zzz/exposed", json={"exposed": True})
    assert r.status_code == 404
