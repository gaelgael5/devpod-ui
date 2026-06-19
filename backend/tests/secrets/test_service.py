from __future__ import annotations

import uuid

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.tables import users
from portal.secrets.service import (
    SecretAlreadyExists,
    SecretNotFound,
    VaultLocked,
    edit_secret,
    list_user_secrets,
    list_user_secrets_by_type,
    register_secret,
    remove_secret,
    reveal_secret,
)
from portal.vault import session as vault_session

pytestmark = pytest.mark.asyncio

_SID = "test-session-xyz"
_MASTER = b"\x02" * 32
_VAL = "ghp_test_token_12345"


async def _user(conn: AsyncConnection, login: str = "alice") -> None:
    await conn.execute(insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4())))


async def test_register_and_list(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)

    await register_secret(
        "alice",
        _SID,
        "gh-token",
        "GitHub PAT",
        "Token GitHub perso",
        "PAT_GITHUB",
        _VAL,
        storage_type="local",
        vault_identifier=None,
        conn=db_conn,
    )
    secrets = await list_user_secrets("alice", db_conn)
    assert len(secrets) == 1
    assert secrets[0]["slug"] == "gh-token"
    # la valeur chiffrée ne doit PAS apparaître dans la liste
    assert "secret_value_local" not in secrets[0]


async def test_register_duplicate_raises(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)

    await register_secret(
        "alice",
        _SID,
        "gh-token",
        "GitHub PAT",
        "",
        "PAT_GITHUB",
        _VAL,
        storage_type="local",
        vault_identifier=None,
        conn=db_conn,
    )
    with pytest.raises(SecretAlreadyExists):
        await register_secret(
            "alice",
            _SID,
            "gh-token",
            "GitHub PAT 2",
            "",
            "PAT_GITHUB",
            _VAL,
            storage_type="local",
            vault_identifier=None,
            conn=db_conn,
        )


async def test_vault_locked_raises(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    vault_session.clear_session("no-session")

    with pytest.raises(VaultLocked):
        await register_secret(
            "alice",
            "no-session",
            "gh-token",
            "GitHub PAT",
            "",
            "PAT_GITHUB",
            _VAL,
            storage_type="local",
            vault_identifier=None,
            conn=db_conn,
        )


async def test_reveal_secret(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)

    await register_secret(
        "alice",
        _SID,
        "gh-token",
        "GitHub PAT",
        "",
        "PAT_GITHUB",
        _VAL,
        storage_type="local",
        vault_identifier=None,
        conn=db_conn,
    )
    plain = await reveal_secret("alice", _SID, "gh-token", db_conn)
    assert plain == _VAL


async def test_edit_secret(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)

    await register_secret(
        "alice",
        _SID,
        "gh-token",
        "GitHub PAT",
        "",
        "PAT_GITHUB",
        _VAL,
        storage_type="local",
        vault_identifier=None,
        conn=db_conn,
    )

    new_val = "ghp_updated_token_99999"
    await edit_secret(
        "alice",
        _SID,
        "gh-token",
        label="GitHub PAT (updated)",
        description="Nouveau token",
        new_value=new_val,
        conn=db_conn,
    )

    plain = await reveal_secret("alice", _SID, "gh-token", db_conn)
    assert plain == new_val

    secrets = await list_user_secrets("alice", db_conn)
    assert secrets[0]["label"] == "GitHub PAT (updated)"


async def test_remove_secret(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)

    await register_secret(
        "alice",
        _SID,
        "gh-token",
        "GitHub PAT",
        "",
        "PAT_GITHUB",
        _VAL,
        storage_type="local",
        vault_identifier=None,
        conn=db_conn,
    )
    await remove_secret("alice", _SID, "gh-token", db_conn)
    secrets = await list_user_secrets("alice", db_conn)
    assert secrets == []


async def test_remove_nonexistent_raises(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)

    with pytest.raises(SecretNotFound):
        await remove_secret("alice", _SID, "ghost", db_conn)


async def test_list_by_type(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)

    await register_secret(
        "alice",
        _SID,
        "gh-token",
        "GitHub PAT",
        "",
        "PAT_GITHUB",
        _VAL,
        storage_type="local",
        vault_identifier=None,
        conn=db_conn,
    )
    await register_secret(
        "alice",
        _SID,
        "openai-key",
        "OpenAI Key",
        "",
        "API_KEY",
        "sk-test-openai-key",
        storage_type="local",
        vault_identifier=None,
        conn=db_conn,
    )

    pat_secrets = await list_user_secrets_by_type("alice", "PAT_GITHUB", db_conn)
    assert len(pat_secrets) == 1
    assert pat_secrets[0]["slug"] == "gh-token"

    api_secrets = await list_user_secrets_by_type("alice", "API_KEY", db_conn)
    assert len(api_secrets) == 1
    assert api_secrets[0]["slug"] == "openai-key"
