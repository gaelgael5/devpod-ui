"""Ancrage de l'identité sur le sub OIDC (users.sub) — résolution + provisioning.

Ces tests exercent la logique DB de resolve_login_by_sub et provision_user :
création avec sub, backfill d'un compte pré-existant, collision (deux subs pour
un même login dérivé), et stabilité (même sub → même login même si le
preferred_username a changé). DB réelle (db_engine).
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from portal.auth.router import provision_user, resolve_login_by_sub
from portal.db.tables import users


@pytest.fixture(autouse=True)
def _db_settings(monkeypatch: pytest.MonkeyPatch, tmp_path):
    import portal.settings as mod

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://ignored@ignored/ignored")
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    mod._settings = None
    yield
    mod._settings = None


async def _sub_of(engine: AsyncEngine, login: str) -> str | None:
    async with engine.connect() as conn:
        return (
            await conn.execute(select(users.c.sub).where(users.c.login == login))
        ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_provision_stores_sub_on_create(db_engine: AsyncEngine, tmp_path):
    await provision_user(login="alice", sub="sub-alice", data_root=tmp_path)
    assert await _sub_of(db_engine, "alice") == "sub-alice"
    assert await resolve_login_by_sub("sub-alice") == "alice"


@pytest.mark.asyncio
async def test_resolve_unknown_sub_is_none(db_engine: AsyncEngine):
    assert await resolve_login_by_sub("sub-inconnu") is None


@pytest.mark.asyncio
async def test_backfill_sub_on_preexisting_row(db_engine: AsyncEngine, tmp_path):
    """Compte pré-existant sans sub (créé avant l'ancrage) → backfill au login."""
    async with db_engine.begin() as conn:
        await conn.execute(
            users.insert().values(
                login="gael", version="1", secret_ns=str(uuid.uuid4())
            )
        )
    await provision_user(login="gael", sub="sub-gael", data_root=tmp_path)
    assert await _sub_of(db_engine, "gael") == "sub-gael"


@pytest.mark.asyncio
async def test_second_login_same_sub_is_stable(db_engine: AsyncEngine, tmp_path):
    """Même sub → même login, idempotent (pas de doublon, pas de collision)."""
    await provision_user(login="alice", sub="sub-alice", data_root=tmp_path)
    await provision_user(login="alice", sub="sub-alice", data_root=tmp_path)
    assert await resolve_login_by_sub("sub-alice") == "alice"


@pytest.mark.asyncio
async def test_collision_different_sub_same_login_raises_403(
    db_engine: AsyncEngine, tmp_path
):
    """Deux personnes dont le preferred_username dérive vers le même login :
    le 2e sub sur le login déjà ancré → 403 (jamais de vol d'identité)."""
    await provision_user(login="alice", sub="sub-alice", data_root=tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        await provision_user(login="alice", sub="sub-mallory", data_root=tmp_path)
    assert exc_info.value.status_code == 403
    # L'ancre d'origine est intacte.
    assert await _sub_of(db_engine, "alice") == "sub-alice"


@pytest.mark.asyncio
async def test_sub_unique_across_logins(db_engine: AsyncEngine, tmp_path):
    """Un même sub ne peut ancrer deux logins distincts (contrainte UNIQUE)."""
    from sqlalchemy.exc import IntegrityError

    await provision_user(login="alice", sub="sub-x", data_root=tmp_path)
    async with db_engine.begin() as conn:
        with pytest.raises(IntegrityError):
            await conn.execute(
                users.insert().values(
                    login="bob", version="1", secret_ns=str(uuid.uuid4()), sub="sub-x"
                )
            )
