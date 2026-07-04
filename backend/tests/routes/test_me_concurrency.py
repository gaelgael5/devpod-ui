"""Bug 009 — lost update sur le cycle load → modify → save de UserConfig.

Sans verrou par login, deux requêtes concurrentes du même user (ex. l'UI
ajoute un workspace pendant qu'un appel MCP en modifie un autre) se
chargent la même config puis la réécrivent intégralement (save_user_db =
delete + réinsertion complète) : la modification du perdant disparaît.

Les handlers sont appelés directement (sans TestClient) avec la couche
store mockée en mémoire ; le sleep dans fake_load élargit la fenêtre
load→save pour forcer l'entrelacement que le verrou doit interdire.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from portal.auth.rbac import UserInfo
from portal.config.models import UserConfig, WorkspaceSpec
from portal.config.store import clear_user_config_locks

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _fresh_locks():
    clear_user_config_locks()
    yield
    clear_user_config_locks()


@pytest.fixture
def fake_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, UserConfig]:
    import portal.routes.me as me_mod

    db: dict[str, UserConfig] = {
        "cfg": UserConfig(version="1", secret_ns=str(uuid.uuid4()))
    }

    async def fake_load(login: str) -> UserConfig:
        cfg = db["cfg"].model_copy(deep=True)
        await asyncio.sleep(0.05)  # élargit la fenêtre load→save
        return cfg

    async def fake_save(login: str, cfg: UserConfig) -> None:
        db["cfg"] = cfg.model_copy(deep=True)

    monkeypatch.setattr(me_mod, "load_user", fake_load)
    monkeypatch.setattr(me_mod, "save_user", fake_save)
    return db


async def test_add_workspace_concurrent_no_lost_update(fake_store) -> None:
    import portal.routes.me as me_mod

    user = UserInfo(login="alice", roles=["dev"])
    ws1 = WorkspaceSpec(name="app1", source="git@github.com:u/r1.git")
    ws2 = WorkspaceSpec(name="app2", source="git@github.com:u/r2.git")

    await asyncio.gather(
        me_mod.add_workspace(workspace=ws1, user=user),
        me_mod.add_workspace(workspace=ws2, user=user),
    )

    names = {w.name for w in fake_store["cfg"].workspaces}
    assert names == {"app1", "app2"}, "sans verrou, l'un des deux ajouts est écrasé"


async def test_delete_and_add_concurrent_no_lost_update(fake_store) -> None:
    """Un delete_workspace concurrent d'un add_workspace : les deux effets tiennent."""
    import portal.routes.me as me_mod

    user = UserInfo(login="alice", roles=["dev"])
    fake_store["cfg"].workspaces.append(
        WorkspaceSpec(name="old", source="git@github.com:u/old.git")
    )
    ws_new = WorkspaceSpec(name="new", source="git@github.com:u/new.git")

    await asyncio.gather(
        me_mod.delete_workspace(name="old", user=user),
        me_mod.add_workspace(workspace=ws_new, user=user),
    )

    names = {w.name for w in fake_store["cfg"].workspaces}
    assert names == {"new"}, "le delete et l'add doivent tous deux survivre"
