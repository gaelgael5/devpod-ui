from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.auth.rbac import UserInfo, require_user
from portal.db.engine import get_conn
from portal.db.mcp import (
    find_apikey_by_hash,
    get_apikey,
    get_backend,
    insert_backend_key,
)
from portal.db.mcp_profiles import insert_profile, list_profile_entries
from portal.db.tables import mcp_backend_key, users
from portal.mcp import models, service
from portal.mcp.runtime_secrets import decrypt_service_key
from portal.routes.mcp_profiles import router as profiles_router
from portal.vault import session as vault_session


async def _user(conn: AsyncConnection, login: str = "alice") -> None:
    await conn.execute(insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4())))


def _profiles_client(conn: AsyncConnection, login: str = "alice") -> AsyncClient:
    """Client ASGI sur le router profils MCP, auth et connexion DB court-circuitées.

    La validation des entries (backend/clé) vit dans la route, pas dans le
    service — on la teste donc à travers le router.
    """
    app = FastAPI()
    app.include_router(profiles_router)
    app.dependency_overrides[require_user] = lambda: UserInfo(login=login, roles=["dev"])
    app.dependency_overrides[get_conn] = lambda: conn
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


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


async def test_create_local_key_encrypts_with_kek(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "portal.settings.get_settings",
        lambda: type("S", (), {"portal_vault_kek": "22" * 32})(),
    )
    await _user(db_conn)
    bid = await service.create_backend(
        db_conn, "alice",
        models.BackendCreate(
            namespace="rag", name="RAG", url="https://rag/mcp", transport="streamable_http"
        ),
    )
    key_body = models.KeyCreate(
        slug="read", description="ro", storage_type="local",
        secret_value="rag-token-123", vault_identifier=None,
    )
    # plus besoin de session vault pour 'local'
    kid = await service.create_backend_key(db_conn, "alice", bid, "no-session", key_body)

    blob = (
        await db_conn.execute(
            select(mcp_backend_key.c.secret_value_local).where(mcp_backend_key.c.id == kid)
        )
    ).scalar_one()
    assert blob != b"rag-token-123"
    assert decrypt_service_key(blob) == "rag-token-123"


async def test_create_key_on_foreign_backend_denied(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "portal.settings.get_settings",
        lambda: type("S", (), {"portal_vault_kek": "22" * 32})(),
    )
    await _user(db_conn)
    await _user(db_conn, "bob")
    bid = await service.create_backend(
        db_conn, "alice",
        models.BackendCreate(
            namespace="rag", name="RAG", url="https://rag/mcp", transport="streamable_http"
        ),
    )
    with pytest.raises(service.NotFound):
        await service.create_backend_key(
            db_conn, "bob", bid, "no-session",
            models.KeyCreate(slug="x", description="", storage_type="local",
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


async def test_profile_entry_rejects_key_from_other_backend(db_conn: AsyncConnection) -> None:
    """Équivalent profils de l'ancien set_grant : clé d'un autre backend refusée (404)."""
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
    await insert_profile(db_conn, id="p1", owner_login="alice", name="Profil test")

    # clé de b2 affectée à une entry sur b1 → refus, aucune entry créée
    async with _profiles_client(db_conn) as client:
        resp = await client.put(f"/mcp/profiles/p1/entries/{b1}", json={"backend_key_id": "kB2"})
    assert resp.status_code == 404
    assert await list_profile_entries(db_conn, "p1") == []


async def test_profile_entry_happy_path(db_conn: AsyncConnection) -> None:
    """Équivalent profils de l'ancien set_grant happy path : entry backend + clé explicite."""
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
    await insert_profile(db_conn, id="p1", owner_login="alice", name="Profil test")

    async with _profiles_client(db_conn) as client:
        resp = await client.put(f"/mcp/profiles/p1/entries/{b1}", json={"backend_key_id": "kB1"})
    assert resp.status_code == 200
    entries = await list_profile_entries(db_conn, "p1")
    assert len(entries) == 1 and entries[0]["backend_key_id"] == "kB1"


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


async def test_set_apikey_profile_happy_path(db_conn: AsyncConnection) -> None:
    """Rattachement apikey → profil (remplace l'ancien grant apikey → backend)."""
    await _user(db_conn)
    await insert_profile(db_conn, id="p1", owner_login="alice", name="Profil test")
    aid, _ = await service.create_apikey(db_conn, "alice", models.ApikeyCreate(label="cli"))

    await service.set_apikey_profile(db_conn, "alice", aid, "p1")
    got = await get_apikey(db_conn, "alice", aid)
    assert got is not None and got["profile_id"] == "p1"


async def test_set_apikey_profile_rejects_foreign_apikey(db_conn: AsyncConnection) -> None:
    """bob ne peut pas rattacher un profil à l'apikey d'alice (NotFound)."""
    await _user(db_conn)
    await _user(db_conn, "bob")
    await insert_profile(db_conn, id="pb", owner_login="bob", name="Profil bob")
    aid, _ = await service.create_apikey(db_conn, "alice", models.ApikeyCreate(label="cli"))

    with pytest.raises(service.NotFound):
        await service.set_apikey_profile(db_conn, "bob", aid, "pb")


async def test_set_apikey_profile_rejects_foreign_profile(db_conn: AsyncConnection) -> None:
    """alice ne peut pas rattacher le profil de bob à sa propre apikey (NotFound)."""
    await _user(db_conn)
    await _user(db_conn, "bob")
    await insert_profile(db_conn, id="pb", owner_login="bob", name="Profil bob")
    aid, _ = await service.create_apikey(db_conn, "alice", models.ApikeyCreate(label="cli"))

    with pytest.raises(service.NotFound):
        await service.set_apikey_profile(db_conn, "alice", aid, "pb")
    got = await get_apikey(db_conn, "alice", aid)
    assert got is not None and got["profile_id"] is None


async def test_profile_entry_public_backend_without_key(db_conn: AsyncConnection) -> None:
    """Backend public (sans auth) : entry valide sans backend_key_id, aucune clé exigée."""
    await _user(db_conn)
    b1 = await service.create_backend(
        db_conn, "alice",
        models.BackendCreate(
            namespace="deepwiki", name="DeepWiki",
            url="https://mcp.deepwiki.com/mcp", transport="streamable_http",
        ),
    )
    await insert_profile(db_conn, id="p1", owner_login="alice", name="Profil test")

    # aucune clé créée pour ce backend : l'entry publique ne doit pas en exiger
    async with _profiles_client(db_conn) as client:
        resp = await client.put(f"/mcp/profiles/p1/entries/{b1}", json={})
    assert resp.status_code == 200

    entries = await list_profile_entries(db_conn, "p1")
    assert len(entries) == 1
    assert entries[0]["backend_id"] == b1
    assert entries[0]["backend_key_id"] is None


async def test_profile_entry_stores_tools_curation(db_conn: AsyncConnection) -> None:
    """L'entry porte la curation `tools` (remplace expose_mode/expose des grants)."""
    await _user(db_conn)
    b1 = await service.create_backend(
        db_conn, "alice",
        models.BackendCreate(
            namespace="rag", name="RAG", url="https://rag/mcp", transport="streamable_http"
        ),
    )
    await insert_profile(db_conn, id="p1", owner_login="alice", name="Profil test")

    async with _profiles_client(db_conn) as client:
        resp = await client.put(
            f"/mcp/profiles/p1/entries/{b1}", json={"tools": ["search", "index"]}
        )
        assert resp.status_code == 200
        entries = await list_profile_entries(db_conn, "p1")
        assert len(entries) == 1
        assert entries[0]["tools"] == ["search", "index"]

        # upsert : on change la curation, la ligne doit être mise à jour (pas de doublon)
        resp = await client.put(f"/mcp/profiles/p1/entries/{b1}", json={"tools": []})
        assert resp.status_code == 200
    entries = await list_profile_entries(db_conn, "p1")
    assert len(entries) == 1
    assert entries[0]["tools"] == []
