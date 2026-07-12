"""Spec 35 §8.6 — route PUT /me/mcp/profiles/{id}/exposed (fail closed au décochage).

La route écrit dans une transaction dédiée committée avant de lancer le resync
(asyncio.create_task) : les tests n'utilisent PAS db_conn (SAVEPOINT non commité,
et son unique connexion poolée bloquerait celle de la route) — seed et
vérifications passent par des transactions engine committées, nettoyées par le
drop_all du teardown de db_engine.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from portal.agents.keys import rotate_workspace_keys
from portal.db.mcp import find_apikey_by_hash
from portal.db.mcp_profiles import get_profile, insert_profile, set_profile_exposed
from portal.db.tables import users
from portal.mcp.service import token_hash

_RESYNC_CALLS: list[tuple[str, set[str] | None]] = []


@pytest.fixture(autouse=True)
def _capture_resync(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, set[str] | None]]:
    """Capture les resyncs planifiés (le vrai resync pousserait du SSH)."""
    import portal.routes.mcp_profiles as mod

    _RESYNC_CALLS.clear()

    async def fake_resync(login: str, only: set[str] | None = None) -> dict[str, list[str]]:
        _RESYNC_CALLS.append((login, only))
        return {"synced": [], "skipped": [], "failed": []}

    monkeypatch.setattr(mod, "resync_owner_workspaces", fake_resync)
    return _RESYNC_CALLS


async def _drain_resync_tasks() -> None:
    import portal.routes.mcp_profiles as mod

    if mod._resync_tasks:
        await asyncio.gather(*mod._resync_tasks, return_exceptions=True)


async def _seed(db_engine: AsyncEngine, *, exposed: bool | None = None) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(
            insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
        )
        await insert_profile(conn, id="p1", owner_login="alice", name="défaut")
        if exposed is not None:
            await set_profile_exposed(conn, "alice", "p1", exposed=exposed)


@pytest.fixture
async def client(db_engine: AsyncEngine) -> AsyncGenerator[AsyncClient, None]:
    from fastapi import FastAPI

    from portal.auth.rbac import UserInfo, require_user
    from portal.routes.mcp_profiles import router

    app = FastAPI()
    app.include_router(router, prefix="/me")
    app.dependency_overrides[require_user] = lambda: UserInfo(login="alice", roles=["dev"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_expose_profile_sets_flag_and_schedules_full_resync(
    client: AsyncClient, db_engine: AsyncEngine
) -> None:
    await _seed(db_engine)

    r = await client.put("/me/mcp/profiles/p1/exposed", json={"exposed": True})
    assert r.status_code == 200
    assert r.json() == {"id": "p1", "exposed": True, "affected_workspaces": []}
    await _drain_resync_tasks()

    async with db_engine.connect() as conn:
        row = await get_profile(conn, "alice", "p1")
    assert row is not None and row["exposed_in_workspaces"] is True
    assert _RESYNC_CALLS == [("alice", None)]


async def test_unexpose_revokes_keys_fail_closed(
    client: AsyncClient, db_engine: AsyncEngine
) -> None:
    await _seed(db_engine, exposed=True)
    async with db_engine.begin() as conn:
        keys = await rotate_workspace_keys(conn, "alice", "alice-api")
    assert len(keys) == 1

    r = await client.put("/me/mcp/profiles/p1/exposed", json={"exposed": False})
    assert r.status_code == 200
    body = r.json()
    assert body["exposed"] is False
    assert body["affected_workspaces"] == ["alice-api"]
    await _drain_resync_tasks()

    # clef révoquée ET committée (fail closed) — visible d'une connexion neuve
    async with db_engine.connect() as conn:
        assert await find_apikey_by_hash(conn, token_hash(keys[0].token)) is None
        row = await get_profile(conn, "alice", "p1")
    assert row is not None and row["exposed_in_workspaces"] is False
    # resync ciblé sur les workspaces affectés
    assert [("alice", {"alice-api"})] == _RESYNC_CALLS


async def test_unexpose_without_keys_schedules_nothing(
    client: AsyncClient, db_engine: AsyncEngine
) -> None:
    await _seed(db_engine)
    r = await client.put("/me/mcp/profiles/p1/exposed", json={"exposed": False})
    assert r.status_code == 200
    await _drain_resync_tasks()
    assert _RESYNC_CALLS == []


async def test_exposed_unknown_profile_404(client: AsyncClient, db_engine: AsyncEngine) -> None:
    await _seed(db_engine)
    r = await client.put("/me/mcp/profiles/zzz/exposed", json={"exposed": True})
    assert r.status_code == 404
