from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.tables import users


@pytest.fixture
async def client(db_conn: AsyncConnection) -> AsyncGenerator[AsyncClient, None]:
    # App minimale avec le seul routeur MCP — évite SessionMiddleware/OIDC
    # (même approche que tests/routes/test_plugins.py).
    from fastapi import FastAPI

    from portal.auth.rbac import UserInfo, require_user
    from portal.db.engine import get_conn
    from portal.routes.mcp import router as mcp_router

    await db_conn.execute(
        insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
    )

    app = FastAPI()
    app.include_router(mcp_router, prefix="/me")
    app.dependency_overrides[require_user] = lambda: UserInfo(login="alice", roles=["dev"])
    app.dependency_overrides[get_conn] = lambda: db_conn

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_backend_create_list_delete(client: AsyncClient) -> None:
    r = await client.post("/me/mcp/backends", json={
        "namespace": "rag", "name": "RAG", "url": "https://rag/mcp", "transport": "streamable_http",
    })
    assert r.status_code == 201
    bid = r.json()["id"]

    r = await client.get("/me/mcp/backends")
    assert r.status_code == 200 and len(r.json()) == 1

    # namespace avec '__' → 422 (rejet à la validation, ne touche pas la DB)
    r = await client.post("/me/mcp/backends", json={
        "namespace": "a__b", "name": "X", "url": "https://x/mcp", "transport": "sse",
    })
    assert r.status_code == 422

    r = await client.delete(f"/me/mcp/backends/{bid}")
    assert r.status_code == 204


async def test_backend_list_includes_health(client: AsyncClient) -> None:
    from portal.mcp.monitor import BackendHealth, reset_health, set_health

    reset_health()
    r = await client.post("/me/mcp/backends", json={
        "namespace": "rag", "name": "RAG", "url": "https://rag/mcp", "transport": "streamable_http",
    })
    bid = r.json()["id"]
    set_health(bid, BackendHealth(status="up"))

    r = await client.get("/me/mcp/backends")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["id"] == bid and body[0]["health"] == "up"

    # backend non monitoré → "unknown"
    reset_health()
    r = await client.get("/me/mcp/backends")
    assert r.json()[0]["health"] == "unknown"


async def test_backend_rejects_duplicate_namespace(client: AsyncClient) -> None:
    # Cas isolé : le POST dupliqué viole la contrainte UNIQUE et avorte la
    # transaction asyncpg ; en test, db_conn est partagé entre les requêtes,
    # donc aucune opération DB ne doit suivre dans le même test (en prod, chaque
    # requête a sa propre transaction et ce problème ne se pose pas).
    payload = {
        "namespace": "rag",
        "name": "RAG",
        "url": "https://rag/mcp",
        "transport": "streamable_http",
    }
    r = await client.post("/me/mcp/backends", json=payload)
    assert r.status_code == 201

    r = await client.post("/me/mcp/backends", json={**payload, "name": "X"})
    assert r.status_code == 409


async def test_catalog_route_exposes_scope(client: AsyncClient, db_conn: AsyncConnection) -> None:
    """Le champ scope (read/write/exec/admin) du registre devpod doit survivre au /catalog."""
    from portal.db.mcp import insert_backend
    from portal.db.mcp_catalog import upsert_primitive

    await insert_backend(
        db_conn, id="devpod-alice", owner_login="alice", namespace="devpod",
        name="DevPod workspaces", url="", transport="internal",
    )
    await upsert_primitive(
        db_conn, backend_id="devpod-alice", kind="tool", original_name="workspace_list",
        definition={"description": "Liste les workspaces.", "scope": "read"},
        definition_hash="h1",
    )
    await upsert_primitive(
        db_conn, backend_id="devpod-alice", kind="tool", original_name="workspace_delete",
        definition={"description": "Supprime un workspace.", "scope": "admin"},
        definition_hash="h2",
    )

    r = await client.get("/me/mcp/backends/devpod-alice/catalog")
    assert r.status_code == 200
    by_name = {t["name"]: t["scope"] for t in r.json()}
    assert by_name == {"workspace_list": "read", "workspace_delete": "admin"}


async def test_catalog_route_scope_null_for_external_backend(
    client: AsyncClient, db_conn: AsyncConnection
) -> None:
    """Un backend externe sans champ scope dans sa définition → scope=null, pas d'erreur."""
    r = await client.post("/me/mcp/backends", json={
        "namespace": "rag", "name": "RAG", "url": "https://rag/mcp", "transport": "streamable_http",
    })
    bid = r.json()["id"]

    from portal.db.mcp_catalog import upsert_primitive

    await upsert_primitive(
        db_conn, backend_id=bid, kind="tool", original_name="search",
        definition={"description": "Recherche."}, definition_hash="h3",
    )

    r = await client.get(f"/me/mcp/backends/{bid}/catalog")
    assert r.status_code == 200
    assert r.json() == [{"name": "search", "description": "Recherche.", "scope": None}]


async def test_apikey_create_returns_clear_once(client: AsyncClient) -> None:
    r = await client.post("/me/mcp/apikeys", json={"label": "cli"})
    assert r.status_code == 201
    body = r.json()
    assert body["token"].startswith("mcpk_")
    # le listing ne ré-expose jamais le clair ni le hash
    r = await client.get("/me/mcp/apikeys")
    assert r.status_code == 200
    assert "token" not in r.json()[0] and "token_hash" not in r.json()[0]


# NOTE : l'ancien test « clé d'un autre backend refusée sur PUT /apikeys/{id}/grants »
# a été retiré : la route grants n'existe plus (refactor profils MCP). Le comportement
# équivalent (PUT /me/mcp/profiles/{id}/entries/{backend_id} → 404) est couvert par
# tests/mcp/test_service.py::test_profile_entry_rejects_key_from_other_backend.
