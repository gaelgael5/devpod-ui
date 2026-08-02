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
    assert r.json() == {
        "id": "p1",
        "exposed": True,
        "affected_workspaces": [],
        "unexposed_profiles": [],
    }
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


# ─── Exclusivité de l'exposition (un seul profil exposé à la fois) ────────────


async def _seed_second_profile(db_engine: AsyncEngine, pid: str = "p2") -> None:
    async with db_engine.begin() as conn:
        await insert_profile(conn, id=pid, owner_login="alice", name=f"profil {pid}")


async def test_expose_unexposes_previous_and_revokes_its_keys(
    client: AsyncClient, db_engine: AsyncEngine
) -> None:
    """Exposer un profil bascule l'exposition : le précédent est décoché et ses
    clefs workspace révoquées (l'utilisateur a confirmé la coupure des agents)."""
    await _seed(db_engine, exposed=True)
    await _seed_second_profile(db_engine)
    async with db_engine.begin() as conn:
        keys = await rotate_workspace_keys(conn, "alice", "alice-api")
    assert len(keys) == 1  # une clef dérivée de p1

    r = await client.put("/me/mcp/profiles/p2/exposed", json={"exposed": True})
    assert r.status_code == 200
    body = r.json()
    assert body["exposed"] is True
    assert body["unexposed_profiles"] == ["défaut"]
    assert body["affected_workspaces"] == ["alice-api"]
    await _drain_resync_tasks()

    async with db_engine.connect() as conn:
        p1 = await get_profile(conn, "alice", "p1")
        p2 = await get_profile(conn, "alice", "p2")
        # clef de l'ancien profil révoquée et committée
        assert await find_apikey_by_hash(conn, token_hash(keys[0].token)) is None
    assert p1 is not None and p1["exposed_in_workspaces"] is False
    assert p2 is not None and p2["exposed_in_workspaces"] is True
    # resync complet : chaque workspace doit recevoir la clef du nouveau profil
    assert _RESYNC_CALLS == [("alice", None)]


async def test_expose_already_exposed_profile_touches_nothing_else(
    client: AsyncClient, db_engine: AsyncEngine
) -> None:
    """Ré-exposer le profil déjà exposé ne décoche personne (pas de coupure inutile)."""
    await _seed(db_engine, exposed=True)
    await _seed_second_profile(db_engine)

    r = await client.put("/me/mcp/profiles/p1/exposed", json={"exposed": True})
    assert r.status_code == 200
    body = r.json()
    assert body["unexposed_profiles"] == []
    assert body["affected_workspaces"] == []
    await _drain_resync_tasks()

    async with db_engine.connect() as conn:
        p1 = await get_profile(conn, "alice", "p1")
        p2 = await get_profile(conn, "alice", "p2")
    assert p1 is not None and p1["exposed_in_workspaces"] is True
    assert p2 is not None and p2["exposed_in_workspaces"] is False


async def test_expose_first_profile_reports_no_previous(
    client: AsyncClient, db_engine: AsyncEngine
) -> None:
    """Aucun profil exposé au départ : rien à décocher, aucune clef révoquée."""
    await _seed(db_engine)
    await _seed_second_profile(db_engine)

    r = await client.put("/me/mcp/profiles/p2/exposed", json={"exposed": True})
    assert r.status_code == 200
    assert r.json()["unexposed_profiles"] == []
    assert r.json()["affected_workspaces"] == []
