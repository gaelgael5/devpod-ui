from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import (
    find_apikey_by_hash,
    get_backend,
    insert_backend_key,
    list_backend_keys,
    list_grants,
)
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


async def test_create_apikey_returns_clear_once_and_stores_hash(
    db_conn: AsyncConnection,
) -> None:
    await _user(db_conn)
    aid, clear = await service.create_apikey(db_conn, "alice", models.ApikeyCreate(label="cli"))
    assert clear.startswith(service.APIKEY_PREFIX)
    # le hash stocké correspond au clair ; le clair n'est pas retrouvable autrement
    found = await find_apikey_by_hash(db_conn, service.token_hash(clear))
    assert found is not None and found["id"] == aid


async def test_set_grant_rejects_key_from_other_backend(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    b1 = await service.create_backend(
        db_conn, "alice",
        models.BackendCreate(
            namespace="rag", name="RAG", url="https://rag/mcp", transport="streamable_http"
        ),
    )
    b2 = await service.create_backend(
        db_conn, "alice",
        models.BackendCreate(
            namespace="wf", name="WF", url="https://wf/mcp", transport="streamable_http"
        ),
    )
    await insert_backend_key(
        db_conn, id="kB2", backend_id=b2, slug="read", description="",
        storage_type="local", secret_value_local=b"x",
        secret_value_vault_ref=None, vault_identifier=None,
    )
    aid, _ = await service.create_apikey(db_conn, "alice", models.ApikeyCreate(label="cli"))

    # clé de b2 affectée à un grant sur b1 → refus
    with pytest.raises(service.InvalidReference):
        await service.set_grant(
            db_conn, "alice", aid, models.GrantSet(backend_id=b1, backend_key_id="kB2")
        )


async def test_set_grant_happy_path(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    b1 = await service.create_backend(
        db_conn, "alice",
        models.BackendCreate(
            namespace="rag", name="RAG", url="https://rag/mcp", transport="streamable_http"
        ),
    )
    await insert_backend_key(
        db_conn, id="kB1", backend_id=b1, slug="read", description="",
        storage_type="local", secret_value_local=b"x",
        secret_value_vault_ref=None, vault_identifier=None,
    )
    aid, _ = await service.create_apikey(db_conn, "alice", models.ApikeyCreate(label="cli"))
    await service.set_grant(
        db_conn, "alice", aid, models.GrantSet(backend_id=b1, backend_key_id="kB1")
    )
    grants = await list_grants(db_conn, aid)
    assert len(grants) == 1 and grants[0]["backend_key_id"] == "kB1"


async def test_create_harpocrate_key_writes_vault_and_stores_ref(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La branche harpocrate écrit la valeur dans le coffre AVANT l'insert DB."""
    await _user(db_conn)
    bid = await service.create_backend(
        db_conn, "alice",
        models.BackendCreate(
            namespace="rag", name="RAG", url="https://rag/mcp", transport="streamable_http"
        ),
    )

    # Faux client Harpocrate qui enregistre les appels
    calls: list[tuple[str, str]] = []

    class _FakeSecrets:
        def create(self, path: str, value: str) -> None:
            calls.append((path, value))

    class _FakeClient:
        secrets = _FakeSecrets()

    async def _fake_get_vault_client(
        login: str, session_id: str, identifier: str, conn: Any
    ) -> _FakeClient:
        return _FakeClient()

    monkeypatch.setattr("portal.mcp.service.get_vault_client", _fake_get_vault_client)

    sid = "sess-harpo"
    vault_session.set_master_key(sid, b"\xAA" * 32)
    try:
        key_body = models.KeyCreate(
            slug="apitoken",
            description="token harpocrate",
            storage_type="harpocrate",
            secret_value="secret-harpo-value",
            vault_identifier="my-vault",
        )
        kid = await service.create_backend_key(db_conn, "alice", bid, sid, key_body)
    finally:
        vault_session.clear_session(sid)

    # (a) l'écriture vault a bien eu lieu avec le bon path et la bonne valeur
    expected_path = f"mcp/{bid}/apitoken/value"
    assert len(calls) == 1, "secrets.create doit être appelé exactement une fois"
    assert calls[0] == (expected_path, "secret-harpo-value")

    # (b) la row stocke la référence vault et secret_value_local reste None
    row = (
        await db_conn.execute(
            select(
                mcp_backend_key.c.secret_value_vault_ref,
                mcp_backend_key.c.secret_value_local,
                mcp_backend_key.c.vault_identifier,
            ).where(mcp_backend_key.c.id == kid)
        )
    ).one()
    expected_ref = f"${{vault://my-vault:{expected_path}}}"
    assert row.secret_value_vault_ref == expected_ref
    assert row.secret_value_local is None
    assert row.vault_identifier == "my-vault"


async def test_create_harpocrate_key_requires_unlocked_vault(db_conn: AsyncConnection) -> None:
    """Vault verrouillé → VaultLocked, même pour storage_type='harpocrate'."""
    await _user(db_conn)
    bid = await service.create_backend(
        db_conn, "alice",
        models.BackendCreate(
            namespace="rag2", name="RAG", url="https://rag/mcp", transport="streamable_http"
        ),
    )
    with pytest.raises(service.VaultLocked):
        await service.create_backend_key(
            db_conn, "alice", bid, "no-session",
            models.KeyCreate(
                slug="tok", description="", storage_type="harpocrate",
                secret_value="v", vault_identifier="my-vault"
            ),
        )


async def test_set_grant_rejects_foreign_apikey(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await _user(db_conn, "bob")
    b1 = await service.create_backend(
        db_conn, "alice",
        models.BackendCreate(
            namespace="rag", name="RAG", url="https://rag/mcp", transport="streamable_http"
        ),
    )
    await insert_backend_key(
        db_conn, id="kB1", backend_id=b1, slug="read", description="",
        storage_type="local", secret_value_local=b"x",
        secret_value_vault_ref=None, vault_identifier=None,
    )
    aid, _ = await service.create_apikey(db_conn, "alice", models.ApikeyCreate(label="cli"))
    # bob tente de greffer un grant sur l'apikey d'alice
    with pytest.raises(service.NotFound):
        await service.set_grant(
            db_conn, "bob", aid, models.GrantSet(backend_id=b1, backend_key_id="kB1")
        )
