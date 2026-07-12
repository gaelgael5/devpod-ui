"""Spec 35b T6 — resync à chaud par écriture conteneur (push monkeypatché).

Le resync ne pousse plus vers le host : il écrit dans les conteneurs RUNNING via
`push_agent_files` (rotation incluse). Un workspace arrêté est sauté — le hook
post-readiness du prochain `up` le rattrapera.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from portal.config.models import GlobalConfig, UserConfig, WorkspaceSpec


def _global_cfg() -> GlobalConfig:
    return GlobalConfig.model_validate(
        {
            "version": "1",
            "server": {
                "base_domain": "dev.yoops.org",
                "external_url": "https://dev.yoops.org",
            },
            "auth": {
                "oidc": {
                    "issuer": "https://kc.test",
                    "client_id": "portal",
                    "client_secret": "",
                }
            },
            "hosts": [
                {
                    "name": "node-ssh",
                    "default": True,
                    "type": "ssh",
                    "address": "debian@192.168.1.40",
                    "host_cert_slug": "node-key",
                },
                {"name": "node-tls", "type": "docker-tls", "docker_host": "tcp://n:2376"},
            ],
        }
    )


def _user_cfg(specs: list[WorkspaceSpec]) -> UserConfig:
    return UserConfig(version="1", secret_ns=str(uuid.uuid4()), workspaces=specs)


@pytest.fixture
def resync_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Environnement resync simulé ; capture les appels à push_agent_files."""
    import portal.agents.resync as mod

    calls: dict[str, Any] = {
        "push": [],
        "cfg": _global_cfg(),
        "user": _user_cfg([]),
        "running": None,  # None = tout est running ; sinon set de ws_id
    }

    async def fake_load_user(login: str) -> UserConfig:
        return calls["user"]

    async def fake_push(**kwargs: Any) -> list[str]:
        if kwargs["ws_id"] in calls.get("fail_for", ()):
            raise RuntimeError("conteneur injoignable")
        calls["push"].append(kwargs)
        return list(kwargs["agents"])

    async def fake_running(ws_id: str) -> bool:
        running = calls["running"]
        return True if running is None else ws_id in running

    monkeypatch.setattr(mod, "load_user", fake_load_user)
    monkeypatch.setattr(mod, "load_global", lambda: calls["cfg"])
    monkeypatch.setattr(mod, "push_agent_files", fake_push)
    monkeypatch.setattr(mod, "_ws_running", fake_running)
    return calls


async def test_resync_pushes_into_agent_workspaces(resync_env: dict[str, Any]) -> None:
    from portal.agents.resync import resync_owner_workspaces

    resync_env["user"] = _user_cfg(
        [
            WorkspaceSpec(name="api", source="", host="node-ssh", agents=["claude"]),
            WorkspaceSpec(name="front", source="", host="node-ssh"),  # sans agents
        ]
    )
    results = await resync_owner_workspaces("alice")
    assert results == {"synced": ["alice-api"], "skipped": [], "failed": []}
    call = resync_env["push"][0]
    assert call["login"] == "alice"
    assert call["ws_id"] == "alice-api"
    assert call["ws_name"] == "api"
    assert call["agents"] == ["claude"]
    assert call["mcp_url"] == "https://dev.yoops.org/mcp/"
    assert call["project_root"] == "/workspaces/alice-api"


async def test_resync_only_filter(resync_env: dict[str, Any]) -> None:
    from portal.agents.resync import resync_owner_workspaces

    resync_env["user"] = _user_cfg(
        [
            WorkspaceSpec(name="api", source="", host="node-ssh", agents=["claude"]),
            WorkspaceSpec(name="doc", source="", host="node-ssh", agents=["claude"]),
        ]
    )
    results = await resync_owner_workspaces("alice", only_ws_ids={"alice-doc"})
    assert results["synced"] == ["alice-doc"]
    assert len(resync_env["push"]) == 1


async def test_resync_skips_docker_tls_host(resync_env: dict[str, Any]) -> None:
    from portal.agents.resync import resync_owner_workspaces

    resync_env["user"] = _user_cfg(
        [WorkspaceSpec(name="api", source="", host="node-tls", agents=["claude"])]
    )
    results = await resync_owner_workspaces("alice")
    assert results == {"synced": [], "skipped": ["alice-api"], "failed": []}


async def test_resync_skips_stopped_workspace(resync_env: dict[str, Any]) -> None:
    from portal.agents.resync import resync_owner_workspaces

    resync_env["user"] = _user_cfg(
        [
            WorkspaceSpec(name="api", source="", host="node-ssh", agents=["claude"]),
            WorkspaceSpec(name="doc", source="", host="node-ssh", agents=["claude"]),
        ]
    )
    resync_env["running"] = {"alice-doc"}
    results = await resync_owner_workspaces("alice")
    # Arrêté = sauté (le prochain up poussera), jamais compté en échec.
    assert results == {"synced": ["alice-doc"], "skipped": ["alice-api"], "failed": []}


async def test_resync_failure_isolated_per_workspace(resync_env: dict[str, Any]) -> None:
    from portal.agents.resync import resync_owner_workspaces

    resync_env["user"] = _user_cfg(
        [
            WorkspaceSpec(name="api", source="", host="node-ssh", agents=["claude"]),
            WorkspaceSpec(name="doc", source="", host="node-ssh", agents=["claude"]),
        ]
    )
    resync_env["fail_for"] = {"alice-api"}
    results = await resync_owner_workspaces("alice")
    assert results["failed"] == ["alice-api"]
    assert results["synced"] == ["alice-doc"]


async def test_boot_reconcile_targets_running_agent_workspaces(
    resync_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import portal.agents.resync as mod
    from portal.agents.resync import reconcile_agents_on_boot

    resync_env["user"] = _user_cfg(
        [
            WorkspaceSpec(name="api", source="", host="node-ssh", agents=["claude"]),
            WorkspaceSpec(name="front", source="", host="node-ssh"),  # sans agents
        ]
    )

    async def fake_list_running() -> list[dict[str, Any]]:
        return [
            {"ws_id": "alice-api", "login": "alice"},
            {"ws_id": "alice-front", "login": "alice"},
        ]

    monkeypatch.setattr(mod, "_list_running", fake_list_running)
    await reconcile_agents_on_boot(throttle_s=0)
    assert [c["ws_id"] for c in resync_env["push"]] == ["alice-api"]


async def test_boot_reconcile_best_effort(
    resync_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import portal.agents.resync as mod
    from portal.agents.resync import reconcile_agents_on_boot

    resync_env["user"] = _user_cfg(
        [WorkspaceSpec(name="api", source="", host="node-ssh", agents=["claude"])]
    )
    resync_env["fail_for"] = {"alice-api"}

    async def fake_list_running() -> list[dict[str, Any]]:
        return [{"ws_id": "alice-api", "login": "alice"}]

    monkeypatch.setattr(mod, "_list_running", fake_list_running)
    # Ne lève jamais : best-effort loggé.
    await reconcile_agents_on_boot(throttle_s=0)
    assert resync_env["push"] == []
