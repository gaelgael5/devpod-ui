"""Spec 35 §8.6 — routes agent-types (CRUD admin, preview, liste user, RBAC).

Le PATCH écrit dans une transaction dédiée (resync post-commit garanti) : les
tests n'utilisent pas db_conn (sa connexion poolée unique bloquerait celle de la
route) — le vrai get_conn travaille sur le moteur de test, données committées,
nettoyées par le drop_all du teardown de db_engine.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from portal.db.tables import users, workspaces


@pytest.fixture(autouse=True)
def _no_resync(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise le resync fire-and-forget (le vrai pousserait du SSH)."""
    import portal.routes.agent_types as mod

    async def fake_resync(agent_id: str) -> dict[str, list[str]]:
        return {"synced": [], "skipped": [], "failed": []}

    monkeypatch.setattr(mod, "resync_agent_type_workspaces", fake_resync)


async def _drain_resync_tasks() -> None:
    import portal.routes.agent_types as mod

    if mod._resync_tasks:
        await asyncio.gather(*mod._resync_tasks, return_exceptions=True)


_CLAUDE = {
    "id": "claude",
    "label": "Claude Code",
    "filename": ".mcp.json",
    "template": '{"mcpServers": {}}',
    "target_path": "{{ project_root }}/.mcp.json",
}


def _make_app(*, admin: bool):
    from fastapi import FastAPI, HTTPException

    from portal.auth.rbac import UserInfo, require_admin, require_user
    from portal.routes.agent_types import admin_router, me_router

    app = FastAPI()
    app.include_router(admin_router, prefix="/admin")
    app.include_router(me_router, prefix="/me")
    app.dependency_overrides[require_user] = lambda: UserInfo(login="alice", roles=["dev"])
    if admin:
        app.dependency_overrides[require_admin] = lambda: UserInfo(login="root", roles=["admin"])
    else:

        def _forbidden() -> UserInfo:
            raise HTTPException(status_code=403, detail="admin requis")

        app.dependency_overrides[require_admin] = _forbidden
    return app


async def _seed_user(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(
            insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
        )


@pytest.fixture
async def admin_client(db_engine: AsyncEngine) -> AsyncGenerator[AsyncClient, None]:
    await _seed_user(db_engine)
    app = _make_app(admin=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.fixture
async def dev_client(db_engine: AsyncEngine) -> AsyncGenerator[AsyncClient, None]:
    await _seed_user(db_engine)
    app = _make_app(admin=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_crud_agent_type(admin_client: AsyncClient) -> None:
    r = await admin_client.post("/admin/agent-types", json=_CLAUDE)
    assert r.status_code == 201

    # doublon → 409
    r = await admin_client.post("/admin/agent-types", json=_CLAUDE)
    assert r.status_code == 409

    r = await admin_client.get("/admin/agent-types")
    assert r.status_code == 200
    assert [t["id"] for t in r.json()] == ["claude"]

    r = await admin_client.patch(
        "/admin/agent-types/claude",
        json={
            "label": "Claude",
            "filename": ".mcp.json",
            "template": "{}",
            "target_path": "{{ project_root }}/.mcp.json",
            "enabled": False,
        },
    )
    assert r.status_code == 200
    await _drain_resync_tasks()

    r = await admin_client.get("/admin/agent-types")
    assert r.json()[0]["label"] == "Claude"
    assert r.json()[0]["enabled"] is False

    r = await admin_client.delete("/admin/agent-types/claude")
    assert r.status_code == 204
    r = await admin_client.delete("/admin/agent-types/claude")
    assert r.status_code == 404


async def test_create_invalid_filename_rejected(admin_client: AsyncClient) -> None:
    r = await admin_client.post("/admin/agent-types", json={**_CLAUDE, "filename": "../evil"})
    assert r.status_code == 422


async def test_delete_refused_when_referenced(
    admin_client: AsyncClient, db_engine: AsyncEngine
) -> None:
    await admin_client.post("/admin/agent-types", json=_CLAUDE)
    async with db_engine.begin() as conn:
        await conn.execute(
            insert(workspaces).values(login="alice", name="api", source="", agents=["claude"])
        )
    r = await admin_client.delete("/admin/agent-types/claude")
    assert r.status_code == 409
    assert "alice-api" in r.json()["detail"]


async def test_preview_renders_with_fake_tokens(admin_client: AsyncClient) -> None:
    await admin_client.post("/admin/agent-types", json=_CLAUDE)
    template = "{% for s in servers %}{{ s.name }}={{ s.token }};{% endfor %}"
    r = await admin_client.post("/admin/agent-types/claude/preview", json={"template": template})
    assert r.status_code == 200
    content = r.json()["content"]
    assert "mcpk_EXEMPLE" in content
    assert "défaut" in content or "defaut" in content or "d-faut" in content


async def test_preview_hostile_template_422(admin_client: AsyncClient) -> None:
    r = await admin_client.post(
        "/admin/agent-types/claude/preview",
        json={"template": "{{ ''.__class__.__mro__ }}"},
    )
    assert r.status_code == 422


async def test_admin_routes_forbidden_for_dev(dev_client: AsyncClient) -> None:
    assert (await dev_client.get("/admin/agent-types")).status_code == 403
    assert (await dev_client.post("/admin/agent-types", json=_CLAUDE)).status_code == 403


async def test_me_lists_enabled_only(admin_client: AsyncClient) -> None:
    await admin_client.post("/admin/agent-types", json=_CLAUDE)
    await admin_client.post(
        "/admin/agent-types",
        json={**_CLAUDE, "id": "codex", "label": "Codex", "enabled": False},
    )
    r = await admin_client.get("/me/agent-types")
    assert r.status_code == 200
    assert r.json() == [{"id": "claude", "label": "Claude Code"}]
