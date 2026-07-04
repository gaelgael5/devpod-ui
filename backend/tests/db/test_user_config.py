"""Tests de la couche persistance UserConfig (Tour 4)."""
from __future__ import annotations

import asyncio
import uuid

import pytest

from portal.config.models import (
    GitCredential,
    HarpocrateUserConfig,
    SourceSpec,
    UserConfig,
    UserDefaults,
    WorkspaceExpose,
    WorkspaceSpec,
)
from portal.db.user_config import ensure_user_db, load_user_db, save_user_db

LOGIN = "testuser"


def _minimal_cfg() -> UserConfig:
    return UserConfig(
        version="1",
        secret_ns=str(uuid.uuid4()),
        defaults=UserDefaults(),
        harpocrate=HarpocrateUserConfig(),
    )


def _full_cfg() -> UserConfig:
    return UserConfig(
        version="1",
        secret_ns=str(uuid.uuid4()),
        defaults=UserDefaults(ide="vscode", idle_timeout="2h"),
        harpocrate=HarpocrateUserConfig(api_key="secret"),
        git_credentials=[
            GitCredential(name="gh", host="github.com", kind="token", token="tok123"),
            GitCredential(name="gl", host="gitlab.com", kind="ssh", key_path="/keys/id"),
        ],
        workspaces=[
            WorkspaceSpec(
                name="ws-one",
                source="https://github.com/org/repo",
                branch="main",
                git_credential="gh",
                recipes=["python", "node"],
                env={"FOO": "bar"},
                expose=WorkspaceExpose(hostname="ws-one.dev.example.com"),
                extra_sources=[
                    SourceSpec(url="https://github.com/org/lib", branch="dev"),
                ],
            ),
        ],
    )


# ─── round-trip ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_and_load_minimal(db_conn):
    cfg = _minimal_cfg()
    await save_user_db(LOGIN, cfg, db_conn)
    loaded = await load_user_db(LOGIN, db_conn)
    assert loaded.secret_ns == cfg.secret_ns
    assert loaded.defaults.ide == "openvscode"
    assert loaded.git_credentials == []
    assert loaded.workspaces == []


@pytest.mark.asyncio
async def test_save_and_load_full(db_conn):
    cfg = _full_cfg()
    await save_user_db(LOGIN, cfg, db_conn)
    loaded = await load_user_db(LOGIN, db_conn)
    assert loaded.defaults.ide == "vscode"
    assert loaded.harpocrate.api_key == "secret"
    assert len(loaded.git_credentials) == 2
    assert loaded.git_credentials[0].name == "gh"
    assert loaded.git_credentials[0].token == "tok123"
    assert len(loaded.workspaces) == 1
    ws = loaded.workspaces[0]
    assert ws.name == "ws-one"
    assert ws.recipes == ["python", "node"]
    assert ws.env == {"FOO": "bar"}
    assert ws.expose.hostname == "ws-one.dev.example.com"
    assert len(ws.extra_sources) == 1
    assert ws.extra_sources[0].url == "https://github.com/org/lib"


@pytest.mark.asyncio
async def test_save_and_load_culture_round_trip(db_conn):
    cfg = _minimal_cfg()
    cfg.culture = "en"
    await save_user_db(LOGIN, cfg, db_conn)
    loaded = await load_user_db(LOGIN, db_conn)
    assert loaded.culture == "en"


@pytest.mark.asyncio
async def test_double_save_updates_in_place(db_conn):
    cfg = _minimal_cfg()
    await save_user_db(LOGIN, cfg, db_conn)
    cfg.defaults.ide = "vscode"
    await save_user_db(LOGIN, cfg, db_conn)
    loaded = await load_user_db(LOGIN, db_conn)
    assert loaded.defaults.ide == "vscode"


@pytest.mark.asyncio
async def test_save_replaces_credentials(db_conn):
    cfg = _full_cfg()
    await save_user_db(LOGIN, cfg, db_conn)
    cfg.git_credentials = [GitCredential(name="new", host="bitbucket.org", kind="token", token="x")]
    await save_user_db(LOGIN, cfg, db_conn)
    loaded = await load_user_db(LOGIN, db_conn)
    assert len(loaded.git_credentials) == 1
    assert loaded.git_credentials[0].name == "new"


@pytest.mark.asyncio
async def test_save_replaces_workspaces(db_conn):
    cfg = _full_cfg()
    await save_user_db(LOGIN, cfg, db_conn)
    cfg.workspaces = []
    await save_user_db(LOGIN, cfg, db_conn)
    loaded = await load_user_db(LOGIN, db_conn)
    assert loaded.workspaces == []


@pytest.mark.asyncio
async def test_load_raises_if_no_user(db_conn):
    with pytest.raises(FileNotFoundError):
        await load_user_db("ghost", db_conn)


# ─── ensure_user_db ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_user_creates_row_when_absent(db_conn, tmp_data_root):
    await ensure_user_db("lazyuser", db_conn)
    loaded = await load_user_db("lazyuser", db_conn)
    assert loaded.version == "1"
    assert loaded.secret_ns  # UUID généré (pas de config.yaml sous tmp_data_root)


@pytest.mark.asyncio
async def test_ensure_user_does_not_overwrite_existing(db_conn, tmp_data_root):
    cfg = _minimal_cfg()
    await save_user_db(LOGIN, cfg, db_conn)
    await ensure_user_db(LOGIN, db_conn)
    loaded = await load_user_db(LOGIN, db_conn)
    assert loaded.secret_ns == cfg.secret_ns


@pytest.mark.asyncio
async def test_ensure_user_concurrent_meme_login_sans_unique_violation(
    db_engine_concurrent, tmp_data_root
):
    """Bug 010 : deux provisions concurrentes du même login. La 2e transaction ne
    voit pas l'INSERT non commité de la 1re (READ COMMITTED) — elle ne doit ni
    lever UniqueViolation ni écraser la ligne de la 1re (do_nothing)."""
    async with (
        db_engine_concurrent.connect() as c1,
        db_engine_concurrent.connect() as c2,
    ):
        await ensure_user_db("raceuser", c1)

        async def _concurrent_ensure() -> None:
            await ensure_user_db("raceuser", c2)
            await c2.commit()

        task = asyncio.create_task(_concurrent_ensure())
        await asyncio.sleep(0.3)
        await c1.commit()
        await asyncio.wait_for(task, timeout=10)

    async with db_engine_concurrent.connect() as c3:
        loaded = await load_user_db("raceuser", c3)
    assert loaded.version == "1"


# ─── Concurrence save_user_db (bug 010) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_save_user_concurrent_meme_login_sans_unique_violation(db_engine_concurrent):
    """Bug 010 : deux save_user_db concurrents du même login ne doivent jamais
    lever UniqueViolation ; le dernier committé gagne."""
    cfg1 = _minimal_cfg()
    cfg2 = _minimal_cfg()
    async with (
        db_engine_concurrent.connect() as c1,
        db_engine_concurrent.connect() as c2,
    ):
        await save_user_db(LOGIN, cfg1, c1)

        async def _concurrent_save() -> None:
            await save_user_db(LOGIN, cfg2, c2)
            await c2.commit()

        task = asyncio.create_task(_concurrent_save())
        await asyncio.sleep(0.3)
        await c1.commit()
        await asyncio.wait_for(task, timeout=10)

    async with db_engine_concurrent.connect() as c3:
        loaded = await load_user_db(LOGIN, c3)
    assert loaded.secret_ns == cfg2.secret_ns


@pytest.mark.asyncio
async def test_extra_sources_order_preserved(db_conn):
    cfg = _full_cfg()
    cfg.workspaces[0].extra_sources = [
        SourceSpec(url="https://b.com/repo"),
        SourceSpec(url="https://a.com/repo"),
    ]
    await save_user_db(LOGIN, cfg, db_conn)
    loaded = await load_user_db(LOGIN, db_conn)
    urls = [s.url for s in loaded.workspaces[0].extra_sources]
    assert urls == ["https://b.com/repo", "https://a.com/repo"]
