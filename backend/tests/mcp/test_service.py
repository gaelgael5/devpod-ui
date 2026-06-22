from __future__ import annotations

import uuid

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import get_backend, list_backend_keys
from portal.db.tables import mcp_backend_key, users
from portal.mcp import models, service
from portal.vault import session as vault_session
from portal.vault.crypto import decrypt_token


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


async def test_create_local_key_encrypts_value(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    body_b = models.BackendCreate(
        namespace="rag", name="RAG", url="https://rag/mcp", transport="streamable_http"
    )
    bid = await service.create_backend(db_conn, "alice", body_b)

    mk = b"\x11" * 32
    sid = "sess-alice"
    vault_session.set_master_key(sid, mk)
    try:
        key_body = models.KeyCreate(
            slug="read", description="ro", storage_type="local",
            secret_value="rag-token-123", vault_identifier=None,
        )
        kid = await service.create_backend_key(db_conn, "alice", bid, sid, key_body)
    finally:
        vault_session.clear_session(sid)

    # la liste n'expose jamais la valeur
    rows = await list_backend_keys(db_conn, bid)
    assert rows[0]["slug"] == "read" and "secret_value_local" not in rows[0]

    # la valeur stockée est bien chiffrée et redéchiffrable avec la master_key
    blob = (
        await db_conn.execute(
            select(mcp_backend_key.c.secret_value_local).where(mcp_backend_key.c.id == kid)
        )
    ).scalar_one()
    assert blob != b"rag-token-123"
    assert decrypt_token(blob, mk) == "rag-token-123"


async def test_create_key_on_foreign_backend_denied(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await _user(db_conn, "bob")
    bid = await service.create_backend(
        db_conn, "alice",
        models.BackendCreate(
            namespace="rag", name="RAG", url="https://rag/mcp", transport="streamable_http"
        ),
    )
    sid = "sess-bob"
    vault_session.set_master_key(sid, b"\x22" * 32)
    try:
        with pytest.raises(service.NotFound):
            await service.create_backend_key(
                db_conn, "bob", bid, sid,
                models.KeyCreate(slug="x", description="", storage_type="local",
                                 secret_value="v", vault_identifier=None),
            )
    finally:
        vault_session.clear_session(sid)


async def test_create_local_key_requires_unlocked_vault(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    bid = await service.create_backend(
        db_conn, "alice",
        models.BackendCreate(
            namespace="rag", name="RAG", url="https://rag/mcp", transport="streamable_http"
        ),
    )
    with pytest.raises(service.VaultLocked):
        await service.create_backend_key(
            db_conn, "alice", bid, "no-session",
            models.KeyCreate(slug="read", description="", storage_type="local",
                             secret_value="v", vault_identifier=None),
        )
