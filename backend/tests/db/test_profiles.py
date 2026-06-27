"""Tests de la couche persistance profiles (Tour 5)."""
from __future__ import annotations

import pytest
from sqlalchemy import insert

from portal.db.profiles import (
    AsyncProfileRepository,
    get_profile_db,
    list_profiles_db,
)
from portal.db.tables import users
from portal.profiles.models import ProfileBody
from portal.profiles.repository import ProfileError

# ─── Helpers ──────────────────────────────────────────────────────────────────

_USER_BODY = ProfileBody(
    name="My Profile",
    description="desc",
    extensions=["ms-python.python"],
    settings={"editor.fontSize": 14},
)

_SHARED_BODY = ProfileBody(
    name="Shared Profile",
    description="shared",
    extensions=[],
    settings={},
)


async def _seed_user(conn, login: str = "alice") -> None:
    """Insère un utilisateur minimal pour satisfaire la FK profiles.login."""
    import uuid

    await conn.execute(
        insert(users).values(
            login=login,
            version="1",
            secret_ns=str(uuid.uuid4()),
            default_ide="openvscode",
            default_idle_timeout="2h",
            harpocrate_api_key="",
        )
    )


# ─── list_profiles_db ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_empty(db_conn):
    result = await list_profiles_db("alice", False, db_conn)
    assert result == []


@pytest.mark.asyncio
async def test_list_shared_visible_to_all(db_conn):
    repo = AsyncProfileRepository()
    await repo.create_shared(_SHARED_BODY)
    result = await list_profiles_db("bob", False, db_conn)
    assert len(result) == 1
    assert result[0].scope == "shared"
    assert result[0].editable is False


@pytest.mark.asyncio
async def test_list_shared_editable_for_admin(db_conn):
    repo = AsyncProfileRepository()
    await repo.create_shared(_SHARED_BODY)
    result = await list_profiles_db("admin", True, db_conn)
    assert len(result) == 1
    assert result[0].editable is True


@pytest.mark.asyncio
async def test_list_user_only_visible_to_owner(db_conn):
    await _seed_user(db_conn, "alice")
    await _seed_user(db_conn, "bob")
    repo = AsyncProfileRepository()
    await repo.create("alice", _USER_BODY)

    alice_result = await list_profiles_db("alice", False, db_conn)
    bob_result = await list_profiles_db("bob", False, db_conn)

    assert any(r.scope == "user" for r in alice_result)
    assert not any(r.scope == "user" for r in bob_result)


# ─── get_profile_db ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_shared_profile(db_conn):
    repo = AsyncProfileRepository()
    created = await repo.create_shared(_SHARED_BODY)
    fetched = await get_profile_db("shared", created.slug, "anyone", db_conn)
    assert fetched.name == _SHARED_BODY.name
    assert fetched.scope == "shared"


@pytest.mark.asyncio
async def test_get_not_found_raises(db_conn):
    with pytest.raises(ProfileError) as exc_info:
        await get_profile_db("shared", "nonexistent", "alice", db_conn)
    assert exc_info.value.code == "not_found"


# ─── create / update / delete user ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_user_profile(db_conn):
    await _seed_user(db_conn)
    repo = AsyncProfileRepository()
    profile = await repo.create("alice", _USER_BODY)
    assert profile.slug == "my-profile"
    assert profile.scope == "user"
    assert profile.extensions == ["ms-python.python"]


@pytest.mark.asyncio
async def test_create_slug_dedup(db_conn):
    await _seed_user(db_conn)
    repo = AsyncProfileRepository()
    p1 = await repo.create("alice", _USER_BODY)
    p2 = await repo.create("alice", _USER_BODY)
    assert p1.slug == "my-profile"
    assert p2.slug == "my-profile-2"


@pytest.mark.asyncio
async def test_update_user_profile(db_conn):
    await _seed_user(db_conn)
    repo = AsyncProfileRepository()
    await repo.create("alice", _USER_BODY)
    updated_body = ProfileBody(name="My Profile", description="updated", extensions=[], settings={})
    updated = await repo.update("alice", "my-profile", updated_body)
    assert updated.description == "updated"
    assert updated.extensions == []


@pytest.mark.asyncio
async def test_update_not_found_raises(db_conn):
    await _seed_user(db_conn)
    repo = AsyncProfileRepository()
    with pytest.raises(ProfileError) as exc_info:
        await repo.update("alice", "ghost", _USER_BODY)
    assert exc_info.value.code == "not_found"


@pytest.mark.asyncio
async def test_delete_user_profile(db_conn):
    await _seed_user(db_conn)
    repo = AsyncProfileRepository()
    await repo.create("alice", _USER_BODY)
    await repo.delete("alice", "my-profile")
    with pytest.raises(ProfileError):
        await get_profile_db("user", "my-profile", "alice", db_conn)


@pytest.mark.asyncio
async def test_delete_not_found_raises(db_conn):
    repo = AsyncProfileRepository()
    with pytest.raises(ProfileError) as exc_info:
        await repo.delete("alice", "ghost")
    assert exc_info.value.code == "not_found"


# ─── fork ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fork_shared_to_user(db_conn):
    await _seed_user(db_conn)
    repo = AsyncProfileRepository()
    shared = await repo.create_shared(_SHARED_BODY)
    forked = await repo.fork("alice", shared.slug)
    assert forked.scope == "user"
    assert forked.name == shared.name
    assert forked.extensions == shared.extensions


# ─── create_shared / update_shared / delete_shared ────────────────────────────


@pytest.mark.asyncio
async def test_create_shared_profile(db_conn):
    repo = AsyncProfileRepository()
    profile = await repo.create_shared(_SHARED_BODY)
    assert profile.slug == "shared-profile"
    assert profile.scope == "shared"


@pytest.mark.asyncio
async def test_update_shared_profile(db_conn):
    repo = AsyncProfileRepository()
    await repo.create_shared(_SHARED_BODY)
    updated_body = ProfileBody(
        name="Shared Profile", description="new desc", extensions=[], settings={}
    )
    updated = await repo.update_shared("shared-profile", updated_body)
    assert updated.description == "new desc"


@pytest.mark.asyncio
async def test_delete_shared_profile(db_conn):
    repo = AsyncProfileRepository()
    await repo.create_shared(_SHARED_BODY)
    await repo.delete_shared("shared-profile")
    with pytest.raises(ProfileError):
        await get_profile_db("shared", "shared-profile", "alice", db_conn)


@pytest.mark.asyncio
async def test_user_profiles_isolated_between_users(db_conn):
    await _seed_user(db_conn, "alice")
    await _seed_user(db_conn, "bob")
    repo = AsyncProfileRepository()
    await repo.create("alice", _USER_BODY)

    with pytest.raises(ProfileError):
        await repo.update("bob", "my-profile", _USER_BODY)
