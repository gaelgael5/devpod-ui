"""Tests de la couche persistance UserConfig (Tour 4)."""
from __future__ import annotations

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
from portal.db.user_config import load_user_db, save_user_db

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
