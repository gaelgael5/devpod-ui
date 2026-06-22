from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import insert_backend_key
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

    # namespace dupliqué → 409
    r = await client.post("/me/mcp/backends", json={
        "namespace": "rag", "name": "X", "url": "https://x/mcp", "transport": "sse",
    })
    assert r.status_code == 409

    # namespace avec '__' → 422
    r = await client.post("/me/mcp/backends", json={
        "namespace": "a__b", "name": "X", "url": "https://x/mcp", "transport": "sse",
    })
    assert r.status_code == 422

    r = await client.delete(f"/me/mcp/backends/{bid}")
    assert r.status_code == 204


async def test_apikey_create_returns_clear_once(client: AsyncClient) -> None:
    r = await client.post("/me/mcp/apikeys", json={"label": "cli"})
    assert r.status_code == 201
    body = r.json()
    assert body["token"].startswith("mcpk_")
    # le listing ne ré-expose jamais le clair ni le hash
    r = await client.get("/me/mcp/apikeys")
    assert r.status_code == 200
    assert "token" not in r.json()[0] and "token_hash" not in r.json()[0]


async def test_grant_key_must_belong_to_backend(
    client: AsyncClient, db_conn: AsyncConnection
) -> None:
    b1 = (
        await client.post(
            "/me/mcp/backends",
            json={
                "namespace": "rag",
                "name": "RAG",
                "url": "https://rag/mcp",
                "transport": "streamable_http",
            },
        )
    ).json()["id"]
    b2 = (
        await client.post(
            "/me/mcp/backends",
            json={
                "namespace": "wf",
                "name": "WF",
                "url": "https://wf/mcp",
                "transport": "streamable_http",
            },
        )
    ).json()["id"]
    # clé insérée directement en DB (évite la dépendance vault dans un test route)
    await insert_backend_key(
        db_conn,
        id="kB2",
        backend_id=b2,
        slug="read",
        description="",
        storage_type="local",
        secret_value_local=b"x",
        secret_value_vault_ref=None,
        vault_identifier=None,
    )
    aid = (await client.post("/me/mcp/apikeys", json={"label": "cli"})).json()["id"]

    # clé de b2 affectée à un grant sur b1 → 422
    r = await client.put(
        f"/me/mcp/apikeys/{aid}/grants",
        json={"backend_id": b1, "backend_key_id": "kB2"},
    )
    assert r.status_code == 422
