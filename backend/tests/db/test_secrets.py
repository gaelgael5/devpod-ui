from __future__ import annotations

import uuid

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.secrets import (
    create_secret,
    delete_secret,
    get_secret,
    get_secret_value_local,
    list_secrets,
    list_secrets_by_type,
    set_secret_public,
    update_secret,
)
from portal.db.tables import users

pytestmark = pytest.mark.asyncio

_SECRET_BYTES = b"\xDE\xAD\xBE\xEF" * 16


async def _user(conn: AsyncConnection, login: str = "alice") -> None:
    await conn.execute(insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4())))


async def test_create_and_list(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await create_secret(
        "alice", "gh-token", "GitHub PAT", "Token GitHub perso",
        "PAT_GITHUB",
        secret_value_local=_SECRET_BYTES,
        secret_value_vault_ref=None,
        storage_type="local",
        vault_identifier=None,
        conn=db_conn,
    )
    rows = await list_secrets("alice", db_conn)
    assert len(rows) == 1
    assert rows[0]["slug"] == "gh-token"
    assert rows[0]["secret_type"] == "PAT_GITHUB"
    # secret_value_local ne doit JAMAIS apparaître dans la liste
    assert "secret_value_local" not in rows[0]


async def test_list_by_type(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await create_secret(
        "alice", "gh-token", "GitHub PAT", "",
        "PAT_GITHUB",
        secret_value_local=_SECRET_BYTES,
        secret_value_vault_ref=None,
        storage_type="local",
        vault_identifier=None,
        conn=db_conn,
    )
    await create_secret(
        "alice", "openai-key", "OpenAI Key", "",
        "API_KEY",
        secret_value_local=_SECRET_BYTES,
        secret_value_vault_ref=None,
        storage_type="local",
        vault_identifier=None,
        conn=db_conn,
    )
    rows = await list_secrets_by_type("alice", "PAT_GITHUB", db_conn)
    assert len(rows) == 1
    assert rows[0]["slug"] == "gh-token"


async def test_list_includes_public(db_conn: AsyncConnection) -> None:
    await _user(db_conn, "alice")
    await _user(db_conn, "bob")
    await create_secret(
        "bob", "shared-key", "Shared Key", "",
        "API_KEY",
        secret_value_local=_SECRET_BYTES,
        secret_value_vault_ref=None,
        storage_type="local",
        vault_identifier=None,
        conn=db_conn,
    )
    await set_secret_public("bob", "shared-key", True, db_conn)
    rows = await list_secrets("alice", db_conn)
    assert any(r["slug"] == "shared-key" for r in rows)


async def test_get_secret_value_local_owner_only(db_conn: AsyncConnection) -> None:
    await _user(db_conn, "alice")
    await _user(db_conn, "bob")
    await create_secret(
        "alice", "priv-secret", "Private Secret", "",
        "API_KEY",
        secret_value_local=_SECRET_BYTES,
        secret_value_vault_ref=None,
        storage_type="local",
        vault_identifier=None,
        conn=db_conn,
    )
    await set_secret_public("alice", "priv-secret", True, db_conn)
    # Le propriétaire peut récupérer la valeur
    owner_val = await get_secret_value_local("alice", "priv-secret", db_conn)
    assert owner_val == _SECRET_BYTES
    # Bob ne peut PAS récupérer la valeur locale d'un secret public qui ne lui appartient pas
    other_val = await get_secret_value_local("bob", "priv-secret", db_conn)
    assert other_val is None


async def test_update_secret(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await create_secret(
        "alice", "mytoken", "Old Label", "",
        "PAT_GITHUB",
        secret_value_local=_SECRET_BYTES,
        secret_value_vault_ref=None,
        storage_type="local",
        vault_identifier=None,
        conn=db_conn,
    )
    new_bytes = b"\xFF" * 32
    updated = await update_secret(
        "alice", "mytoken",
        label="New Label",
        description="Nouvelle description",
        secret_value_local=new_bytes,
        secret_value_vault_ref=None,
        conn=db_conn,
    )
    assert updated is True
    row = await get_secret("alice", "mytoken", db_conn)
    assert row is not None
    assert row["label"] == "New Label"
    assert row["description"] == "Nouvelle description"
    val = await get_secret_value_local("alice", "mytoken", db_conn)
    assert val == new_bytes


async def test_delete_returns_row(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await create_secret(
        "alice", "to-delete", "Delete Me", "",
        "API_KEY",
        secret_value_local=_SECRET_BYTES,
        secret_value_vault_ref=None,
        storage_type="local",
        vault_identifier=None,
        conn=db_conn,
    )
    row = await delete_secret("alice", "to-delete", db_conn)
    assert row is not None
    assert row["slug"] == "to-delete"
    remaining = await list_secrets("alice", db_conn)
    assert remaining == []


async def test_is_own_flag(db_conn: AsyncConnection) -> None:
    await _user(db_conn, "alice")
    await _user(db_conn, "bob")
    await create_secret(
        "bob", "bob-public", "Bob Public", "",
        "API_KEY",
        secret_value_local=_SECRET_BYTES,
        secret_value_vault_ref=None,
        storage_type="local",
        vault_identifier=None,
        conn=db_conn,
    )
    await set_secret_public("bob", "bob-public", True, db_conn)
    # alice voit le secret public de bob
    rows = await list_secrets("alice", db_conn)
    assert len(rows) == 1
    bob_row = rows[0]
    assert bob_row["is_own"] is False
    # bob voit son propre secret
    bob_rows = await list_secrets("bob", db_conn)
    assert len(bob_rows) == 1
    assert bob_rows[0]["is_own"] is True
