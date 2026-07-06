"""Spec 35 §3 — resync à chaud des workspaces à agents (couche sync monkeypatchée)."""

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
    """Monte un environnement resync entièrement simulé ; retourne les appels captés."""
    import portal.agents.provisioning as prov
    import portal.agents.resync as mod
    import portal.devpod.service as svc

    calls: dict[str, Any] = {"sync": [], "cfg": _global_cfg(), "user": _user_cfg([])}

    async def fake_load_user(login: str) -> UserConfig:
        return calls["user"]

    async def fake_materialize(slug: str, login: str = "") -> str:
        return f"/tmp/keys/{slug}.pem"

    async def fake_load_types(agents: list[str]) -> list[dict[str, Any]]:
        return [{"id": a, "filename": "f", "template": "{}", "target_path": "/t"} for a in agents]

    async def fake_sync(**kwargs: Any) -> str:
        if kwargs["ws_id"] in calls.get("fail_for", ()):
            raise RuntimeError("host injoignable")
        calls["sync"].append(kwargs)
        return "/home/debian"

    monkeypatch.setattr(mod, "load_user", fake_load_user)
    monkeypatch.setattr(mod, "load_global", lambda: calls["cfg"])
    monkeypatch.setattr(svc, "_materialize_system_cert", fake_materialize)
    monkeypatch.setattr(prov, "_load_requested_agent_types", fake_load_types)
    monkeypatch.setattr(prov, "sync_agent_config", fake_sync)
    return calls


async def test_resync_owner_syncs_agent_workspaces(resync_env: dict[str, Any]) -> None:
    from portal.agents.resync import resync_owner_workspaces

    resync_env["user"] = _user_cfg(
        [
            WorkspaceSpec(name="api", source="", host="node-ssh", agents=["claude"]),
            WorkspaceSpec(name="front", source="", host="node-ssh"),  # sans agents
        ]
    )
    results = await resync_owner_workspaces("alice")
    assert results == {"synced": ["alice-api"], "skipped": [], "failed": []}
    call = resync_env["sync"][0]
    assert call["ws_id"] == "alice-api"
    assert call["ssh_user"] == "debian"
    assert call["ssh_host"] == "192.168.1.40"
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
    assert len(resync_env["sync"]) == 1


async def test_resync_skips_docker_tls_host(resync_env: dict[str, Any]) -> None:
    from portal.agents.resync import resync_owner_workspaces

    resync_env["user"] = _user_cfg(
        [WorkspaceSpec(name="api", source="", host="node-tls", agents=["claude"])]
    )
    results = await resync_owner_workspaces("alice")
    assert results == {"synced": [], "skipped": ["alice-api"], "failed": []}


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
