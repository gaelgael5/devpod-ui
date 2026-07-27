"""Rapprochement de compte par email au login OIDC (resolve_login_by_email)."""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine

from portal.auth.router import resolve_login_by_email
from portal.db.tables import users


async def _seed_user(engine: AsyncEngine, login: str, email: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            users.insert().values(
                login=login, version="1", secret_ns=str(uuid.uuid4()), email=email
            )
        )


@pytest.fixture(autouse=True)
def _database_url(monkeypatch: pytest.MonkeyPatch):
    """Le garde `get_settings().database_url` doit être vrai ; l'engine réel est
    celui installé par la fixture db_engine (module portal.db.engine)."""
    import portal.settings as mod

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://ignored@ignored/ignored")
    mod._settings = None
    yield
    mod._settings = None


@pytest.mark.asyncio
async def test_no_email_returns_none(db_engine: AsyncEngine) -> None:
    assert await resolve_login_by_email("") is None


@pytest.mark.asyncio
async def test_no_match_returns_none(db_engine: AsyncEngine) -> None:
    await _seed_user(db_engine, "alice", "alice@x.io")
    assert await resolve_login_by_email("inconnu@x.io") is None


@pytest.mark.asyncio
async def test_single_match_returns_existing_login(db_engine: AsyncEngine) -> None:
    await _seed_user(db_engine, "alice", "gael@x.io")
    assert await resolve_login_by_email("gael@x.io") == "alice"


@pytest.mark.asyncio
async def test_email_verified_false_skips_match(db_engine: AsyncEngine) -> None:
    """Anti-usurpation : un email explicitement non vérifié ne rattache jamais."""
    await _seed_user(db_engine, "alice", "gael@x.io")
    assert await resolve_login_by_email("gael@x.io", email_verified=False) is None


@pytest.mark.asyncio
async def test_email_verified_true_matches(db_engine: AsyncEngine) -> None:
    await _seed_user(db_engine, "alice", "gael@x.io")
    assert await resolve_login_by_email("gael@x.io", email_verified=True) == "alice"


@pytest.mark.asyncio
async def test_ambiguous_email_raises_403(db_engine: AsyncEngine) -> None:
    await _seed_user(db_engine, "alice", "dup@x.io")
    await _seed_user(db_engine, "bob", "dup@x.io")
    with pytest.raises(HTTPException) as exc_info:
        await resolve_login_by_email("dup@x.io")
    assert exc_info.value.status_code == 403
