from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from asgi_lifespan import LifespanManager
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.exceptions import McpError
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.applications import Starlette

from portal.db.mcp import insert_apikey, set_grant
from portal.db.mcp_audit import list_for_owner
from portal.db.mcp_catalog import upsert_primitive
from portal.db.tables import mcp_backend, users
from portal.mcp.handlers import GATEWAY_LIST_BACKENDS
from portal.mcp.server import build_server
from portal.mcp.service import token_hash

# ─── Helpers ─────────────────────────────────────────────────────────────────

_MCP_BASE = "http://test"


def _build_app() -> tuple[Starlette, StreamableHTTPSessionManager]:
    """Monte un serveur MCP minimal sans le lifespan complet du portail."""
    _server, manager = build_server()

    @contextlib.asynccontextmanager
    async def _lifespan(app: Starlette) -> AsyncIterator[None]:  # noqa: ARG001
        async with manager.run():
            yield

    app = Starlette(lifespan=_lifespan)
    app.mount("/mcp", StreamableHTTPASGIApp(manager))
    return app, manager


def _http_client(app: Starlette, *, bearer: str | None = None) -> httpx.AsyncClient:
    """Construit un httpx.AsyncClient branché sur l'app ASGI via ASGITransport.

    create_mcp_http_client n'accepte pas transport= ; on construit le client
    directement et on le passe en http_client= à streamable_http_client.
    """
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=_MCP_BASE,
        headers=headers,
        follow_redirects=True,
    )


# ─── Tests ───────────────────────────────────────────────────────────────────


async def test_mcp_endpoint_lists_native_tool_with_valid_bearer(
    db_engine: AsyncEngine,
) -> None:
    """Bearer valide → initialize + tools/list retourne le tool natif gateway__list_backends."""
    async with db_engine.begin() as conn:
        await conn.execute(
            insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
        )
        await insert_apikey(
            conn, id="ak1", owner_login="alice", token_hash=token_hash("mcpk_secret"), label=""
        )

    app, _manager = _build_app()
    async with LifespanManager(app):
        http_client = _http_client(app, bearer="mcpk_secret")
        async with (
            http_client,
            streamable_http_client(_MCP_BASE + "/mcp/", http_client=http_client) as (
                read,
                write,
                _get_sid,
            ),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.list_tools()
            names = {t.name for t in result.tools}
            assert GATEWAY_LIST_BACKENDS in names


async def test_mcp_endpoint_rejects_missing_bearer(
    db_engine: AsyncEngine,
) -> None:
    """Requête sans Authorization → tools/list lève une erreur MCP (auth refusée)."""
    # db_engine est requis pour démarrer l'engine global, pas de seed nécessaire.
    app, _manager = _build_app()
    async with LifespanManager(app):
        http_client = _http_client(app)  # pas de bearer
        async with (
            http_client,
            streamable_http_client(_MCP_BASE + "/mcp/", http_client=http_client) as (
                read,
                write,
                _get_sid,
            ),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            with pytest.raises(McpError):
                await session.list_tools()


async def test_call_tool_denied_audit_is_durable(
    db_engine: AsyncEngine,
) -> None:
    """Durabilité de l'audit : un call_tool refusé (outil inconnu) persiste sa ligne d'audit.

    Ce test valide que le handler _call_tool commit explicitement la transaction même
    quand execute_tool_call lève McpError — ce que begin() + rollback-on-exception cassait.

    Note SDK (mcp 1.28) : le low-level server enveloppe toute exception du handler dans
    CallToolResult(isError=True) au lieu de la propager comme McpError côté client.
    On observe donc isError=True sur le résultat, pas une exception levée.
    """
    async with db_engine.begin() as conn:
        await conn.execute(
            insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
        )
        await insert_apikey(
            conn, id="ak1", owner_login="alice", token_hash=token_hash("mcpk_secret"), label=""
        )

    app, _manager = _build_app()
    async with LifespanManager(app):
        http_client = _http_client(app, bearer="mcpk_secret")
        async with (
            http_client,
            streamable_http_client(_MCP_BASE + "/mcp/", http_client=http_client) as (
                read,
                write,
                _get_sid,
            ),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            # Appel d'un outil inexistant → denied → le SDK enveloppe l'exception dans
            # CallToolResult(isError=True) ; aucune exception McpError n'est levée côté client.
            result = await session.call_tool("ghost__nope", {})
            assert result.isError is True

    # Nouvelle connexion indépendante pour prouver la persistance (hors transaction du handler)
    async with db_engine.begin() as conn:
        audit = await list_for_owner(conn, "alice")
    assert len(audit) == 1
    assert audit[0]["status"] == "denied"


async def test_mcp_endpoint_lists_resources_and_prompts(
    db_engine: AsyncEngine,
) -> None:
    """Bearer valide + catalogue seedé → list_prompts et list_resources retournent les primitives
    namespacées (rag__welcome / gw+rag URI)."""
    async with db_engine.begin() as conn:
        await conn.execute(
            insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
        )
        await insert_apikey(
            conn, id="ak1", owner_login="alice", token_hash=token_hash("mcpk_secret"), label=""
        )
        await conn.execute(
            insert(mcp_backend).values(
                id="b1",
                owner_login="alice",
                namespace="rag",
                name="RAG",
                url="https://rag/mcp",
                transport="streamable_http",
            )
        )
        await set_grant(conn, apikey_id="ak1", backend_id="b1", backend_key_id=None)
        await upsert_primitive(
            conn,
            backend_id="b1",
            kind="prompt",
            original_name="welcome",
            definition={"name": "welcome"},
            definition_hash="p1",
        )
        await upsert_primitive(
            conn,
            backend_id="b1",
            kind="resource",
            original_name="resource://foo",
            definition={"uri": "resource://foo", "name": "Foo"},
            definition_hash="r1",
        )

    app, _manager = _build_app()
    async with LifespanManager(app):
        http_client = _http_client(app, bearer="mcpk_secret")
        async with (
            http_client,
            streamable_http_client(_MCP_BASE + "/mcp/", http_client=http_client) as (
                read,
                write,
                _get_sid,
            ),
            ClientSession(read, write) as session,
        ):
            await session.initialize()

            prompts = await session.list_prompts()
            assert any(p.name == "rag__welcome" for p in prompts.prompts)

            resources = await session.list_resources()
            assert any(str(r.uri).startswith("gw+rag") for r in resources.resources)
