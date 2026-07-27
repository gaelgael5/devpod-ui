"""Resync des collecteurs Alloy déployés (env LOKI_URL + config figés au déploiement).

Sans resync, un changement de `loki_push_url` (IP DHCP qui dérive) ou un bump du
template builtin (fix journald) ne touche jamais les collecteurs existants : ils
poussent dans le vide jusqu'à un redéploiement manuel. Le resync réécrit .env +
fichiers + compose sur chaque host et force la recréation, best-effort.
"""

from __future__ import annotations

from typing import Any

import pytest

from portal.compose import service as svc
from portal.compose.models import ComposeDeployment, ComposeTemplate


def _tpl() -> ComposeTemplate:
    return ComposeTemplate(
        id="alloy-collector",
        name="Collecteur de logs (Alloy)",
        description="",
        tags=["builtin"],
        version="3",
        compose_content="services:\n  alloy:\n    image: grafana/alloy:v1.5.1\n",
        parameters=[],
        source="builtin",
        extra_files={"config.alloy": "// v3 journald=/var/log/journal"},
    )


def _dep(uid: str, node: str) -> ComposeDeployment:
    return ComposeDeployment(
        uid=uid,
        id="alloy-collector",
        template_id="alloy-collector",
        template_version="2",
        node_id=node,
        owner_login="admin",
        env_values={},
        host_ports=[],
        status="running",
    )


class _Host:
    def __init__(self, name: str) -> None:
        self.name = name
        self.type = "ssh"
        self.usage = "autres"
        self.address = f"debian@{name}.lan"
        self.host_cert_slug = f"host.{name}.cert"


class _Cfg:
    def __init__(self, hosts: list[_Host], push_url: str | None) -> None:
        self.hosts = hosts

        class _Logs:
            enabled = bool(push_url)
            loki_push_url = push_url
            module = "devpod"

        self.logs = _Logs()


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {"writes": [], "cmds": [], "versions": [], "fail_hosts": set()}

    async def _get_template(conn: Any, tpl_id: str) -> ComposeTemplate | None:
        return _tpl()

    async def _list(conn: Any, *, owner_login: str | None) -> list[ComposeDeployment]:
        return [_dep("u1", "workflow"), _dep("u2", "node1")]

    async def _write(host: Any, path: str, content: str) -> None:
        if host.name in calls["fail_hosts"]:
            raise RuntimeError("host down")
        calls["writes"].append((host.name, path, content))

    async def _run(host: Any, command: str, timeout: float = 300.0) -> tuple[int, str, str]:
        if host.name in calls["fail_hosts"]:
            raise RuntimeError("host down")
        calls["cmds"].append((host.name, command))
        return 0, "", ""

    async def _update_version(conn: Any, uid: str, version: str) -> None:
        calls["versions"].append((uid, version))

    async def _load_user(login: str) -> Any:
        class _U:
            secret_ns = "ns-1"

        return _U()

    monkeypatch.setattr(svc, "get_template", _get_template)
    monkeypatch.setattr(svc, "list_deployments", _list)
    monkeypatch.setattr(svc, "write_host_file", _write)
    monkeypatch.setattr(svc, "run_host_command", _run)
    monkeypatch.setattr(svc, "update_deployment_template_version", _update_version)
    monkeypatch.setattr(svc, "load_user", _load_user)
    monkeypatch.setattr(
        svc, "load_global", lambda: _Cfg([_Host("workflow"), _Host("node1")], "http://loki:3100/p")
    )
    return calls


async def test_resync_rewrites_env_and_files_and_recreates(wired: dict[str, Any]) -> None:
    res = await svc.resync_collector_deployments(conn=object())

    assert res["synced"] == ["u1", "u2"]
    # .env réécrit avec le LOKI_URL courant + fichiers du template v3
    env_writes = [w for w in wired["writes"] if w[1].endswith("/.env")]
    assert len(env_writes) == 2
    assert all("http://loki:3100/p" in w[2] for w in env_writes)
    cfg_writes = [w for w in wired["writes"] if w[1].endswith("/config.alloy")]
    assert all("v3 journald" in w[2] for w in cfg_writes)
    # Recréation forcée (fichier bind-mount changé ≠ recreate automatique)
    assert all("up -d --force-recreate" in c for _h, c in wired["cmds"])
    # Version du template tracée sur la row
    assert wired["versions"] == [("u1", "3"), ("u2", "3")]


async def test_resync_best_effort_per_host(wired: dict[str, Any]) -> None:
    wired["fail_hosts"].add("workflow")
    res = await svc.resync_collector_deployments(conn=object())
    assert res["failed"] == ["u1"]
    assert res["synced"] == ["u2"]


async def test_resync_noop_when_logs_disabled(
    wired: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(svc, "load_global", lambda: _Cfg([_Host("workflow")], None))
    res = await svc.resync_collector_deployments(conn=object())
    assert res == {"synced": [], "failed": [], "skipped": ["u1", "u2"]}
    assert wired["writes"] == []
