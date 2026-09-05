from __future__ import annotations

import pytest
import yaml

from portal.config.models import GlobalConfig
from portal.config.store import (
    ensure_user_dir,
    load_user_config,
    safe_login_path,
    safe_user_path,
)

# ─── safe_user_path ───────────────────────────────────────────────────────────


def test_safe_user_path_returns_correct_path(tmp_data_root):
    p = safe_user_path("alice", "config.yaml")
    assert p == tmp_data_root / "users" / "alice" / "config.yaml"


def test_safe_user_path_no_parts_returns_user_dir(tmp_data_root):
    p = safe_user_path("alice")
    assert p == tmp_data_root / "users" / "alice"


def test_safe_user_path_rejects_dotdot(tmp_data_root):
    with pytest.raises(ValueError, match="Invalid path component"):
        safe_user_path("alice", "..", "etc", "passwd")


def test_safe_user_path_rejects_slash_in_part(tmp_data_root):
    with pytest.raises(ValueError, match="Invalid path component"):
        safe_user_path("alice", "keys/git")


def test_safe_user_path_rejects_invalid_login(tmp_data_root):
    with pytest.raises(ValueError, match="Invalid login"):
        safe_user_path("../evil", "config.yaml")


def test_safe_user_path_rejects_login_with_slash(tmp_data_root):
    with pytest.raises(ValueError, match="Invalid login"):
        safe_user_path("alice/bob", "config.yaml")


# ─── safe_login_path (bug 033) ────────────────────────────────────────────────


def test_safe_login_path_returns_correct_path(tmp_data_root):
    p = safe_login_path("logs", "alice", "alice-dev.log")
    assert p == tmp_data_root / "logs" / "alice" / "alice-dev.log"


def test_safe_login_path_users_root_matches_safe_user_path(tmp_data_root):
    assert safe_login_path("users", "alice", "config.yaml") == safe_user_path(
        "alice", "config.yaml"
    )


def test_safe_login_path_rejects_dotdot(tmp_data_root):
    with pytest.raises(ValueError, match="Invalid path component"):
        safe_login_path("logs", "alice", "..", "etc", "passwd")


def test_safe_login_path_rejects_slash_in_part(tmp_data_root):
    with pytest.raises(ValueError, match="Invalid path component"):
        safe_login_path("logs", "alice", "sub/dir.log")


def test_safe_login_path_rejects_invalid_login(tmp_data_root):
    with pytest.raises(ValueError, match="Invalid login"):
        safe_login_path("logs", "../evil", "x.log")


# ─── ensure_user_dir ──────────────────────────────────────────────────────────


def test_ensure_user_dir_creates_all_subdirs(tmp_data_root):
    ensure_user_dir("alice")
    expected = [
        tmp_data_root / "users" / "alice",
        tmp_data_root / "users" / "alice" / "keys" / "git",
        tmp_data_root / "users" / "alice" / "keys" / "workspaces",
        tmp_data_root / "users" / "alice" / "recipes",
        tmp_data_root / "users" / "alice" / "templates",
        tmp_data_root / "users" / "alice" / "devpod",
    ]
    for d in expected:
        assert d.is_dir(), f"Missing: {d}"


def test_ensure_user_dir_is_idempotent(tmp_data_root):
    ensure_user_dir("alice")
    ensure_user_dir("alice")  # pas d'erreur


# ─── load_user / save_user ────────────────────────────────────────────────────
# Les tests « fichier YAML » d'origine testaient un comportement DISPARU : la
# config utilisateur vit en base depuis la migration correspondante, et le
# round-trip save/load — atomicité transactionnelle comprise — est couvert par
# tests/db/test_user_config.py contre le vrai schéma. Reste ICI ce qui est
# propre à ce module : la validation croisée de load_user_config, testée en
# pur (load_user doublé) — elle ne dépend d'aucun stockage.


# ─── load_user_config (validation croisée) ────────────────────────────────────


@pytest.fixture
def sample_global_config(global_config_yaml: str) -> GlobalConfig:
    return GlobalConfig.model_validate(yaml.safe_load(global_config_yaml))


def _user_cfg(**ws_extra):
    from portal.config.models import UserConfig, WorkspaceSpec

    return UserConfig(
        version="1",
        secret_ns="a3f8c1d2-4b56-7890-abcd-ef1234567890",
        git_credentials=[],
        workspaces=[WorkspaceSpec(name="myws", source="git@github.com:foo/bar.git", **ws_extra)],
    )


@pytest.fixture
def _doubler_load_user(monkeypatch):
    """Injecte la config utilisateur SANS stockage : la validation croisée est
    pure, la doubler contre la base ne prouverait rien de plus."""
    import portal.config.store as store

    def poser(cfg):
        async def _load_user(login: str):
            return cfg

        monkeypatch.setattr(store, "load_user", _load_user)

    return poser


async def test_load_user_config_passes_when_host_exists(sample_global_config, _doubler_load_user):
    _doubler_load_user(_user_cfg(host="local"))

    cfg = await load_user_config("alice", sample_global_config)

    assert cfg.workspaces[0].host == "local"


async def test_load_user_config_rejects_unknown_host(sample_global_config, _doubler_load_user):
    _doubler_load_user(_user_cfg(host="nonexistent-host"))

    with pytest.raises(ValueError, match="nonexistent-host"):
        await load_user_config("alice", sample_global_config)


async def test_load_user_config_rejects_unknown_git_credential(
    sample_global_config, _doubler_load_user
):
    _doubler_load_user(_user_cfg(git_credential="ghost-cred"))

    with pytest.raises(ValueError, match="ghost-cred"):
        await load_user_config("alice", sample_global_config)


# ─── save_global : cache peuplé seulement après COMMIT (bug 034) ──────────────


class _FakeConnCM:
    def __init__(self, events: list) -> None:
        self._events = events

    async def __aenter__(self) -> object:
        self._events.append("begin_enter")
        return object()

    async def __aexit__(self, *exc: object) -> None:
        self._events.append("begin_exit")


class _FakeEngine:
    def __init__(self, events: list) -> None:
        self._events = events

    def begin(self) -> _FakeConnCM:
        return _FakeConnCM(self._events)


@pytest.mark.asyncio
async def test_save_global_populates_cache_only_after_commit(
    monkeypatch, sample_global_config
) -> None:
    import portal.config.store as store_mod
    import portal.db.engine as engine_mod
    import portal.db.global_config as gc_mod

    events: list = []
    monkeypatch.setattr(engine_mod, "_get_engine", lambda: _FakeEngine(events))

    async def fake_save_global_db(cfg, conn):
        events.append("save_global_db")

    monkeypatch.setattr(gc_mod, "save_global_db", fake_save_global_db)
    monkeypatch.setattr(gc_mod, "set_cached_global", lambda cfg: events.append("set_cached_global"))

    await store_mod.save_global(sample_global_config)

    assert events == ["begin_enter", "save_global_db", "begin_exit", "set_cached_global"]


@pytest.mark.asyncio
async def test_save_global_does_not_update_cache_if_commit_fails(
    monkeypatch, sample_global_config
) -> None:
    import portal.config.store as store_mod
    import portal.db.engine as engine_mod
    import portal.db.global_config as gc_mod

    class _FailingConnCM(_FakeConnCM):
        async def __aexit__(self, *exc: object) -> None:
            self._events.append("begin_exit_failed")
            raise RuntimeError("commit failed")

    class _FailingEngine(_FakeEngine):
        def begin(self) -> _FailingConnCM:
            return _FailingConnCM(self._events)

    events: list = []
    monkeypatch.setattr(engine_mod, "_get_engine", lambda: _FailingEngine(events))

    async def fake_save_global_db(cfg, conn):
        events.append("save_global_db")

    monkeypatch.setattr(gc_mod, "save_global_db", fake_save_global_db)
    monkeypatch.setattr(gc_mod, "set_cached_global", lambda cfg: events.append("set_cached_global"))

    with pytest.raises(RuntimeError, match="commit failed"):
        await store_mod.save_global(sample_global_config)

    assert "set_cached_global" not in events
