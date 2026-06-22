from __future__ import annotations

import uuid

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import get_backend
from portal.db.tables import users
from portal.mcp import models, service


async def _user(conn: AsyncConnection, login: str = "alice") -> None:
    await conn.execute(insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4())))


def test_namespace_rejects_double_underscore() -> None:
    with pytest.raises(ValueError):
        models.BackendCreate(
            namespace="rag__x", name="n", url="https://x/mcp", transport="streamable_http"
        )


def test_namespace_rejects_uppercase() -> None:
    with pytest.raises(ValueError):
        models.BackendCreate(
            namespace="RAG", name="n", url="https://x/mcp", transport="streamable_http"
        )


def test_transport_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        models.BackendCreate(namespace="rag", name="n", url="https://x/mcp", transport="grpc")


def test_namespace_accepts_single_underscore() -> None:
    b = models.BackendCreate(namespace="rag_v2", name="n", url="https://x/mcp", transport="sse")
    assert b.namespace == "rag_v2"


async def test_create_backend_then_duplicate_namespace(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    body = models.BackendCreate(
        namespace="rag", name="RAG", url="https://rag/mcp", transport="streamable_http"
    )
    bid = await service.create_backend(db_conn, "alice", body)
    assert (await get_backend(db_conn, "alice", bid))["namespace"] == "rag"

    with pytest.raises(service.NamespaceTaken):
        await service.create_backend(db_conn, "alice", body)
