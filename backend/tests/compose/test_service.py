"""Tests du service lifecycle compose (spec 26 §5)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from portal.compose import service
from portal.compose.models import ComposeParam, ComposeTemplate


def test_parse_ps_status_running() -> None:
    js = '{"Name":"a","State":"running"}\n{"Name":"b","State":"running"}'
    assert service._parse_ps_status(js) == "running"


def test_parse_ps_status_partial() -> None:
    js = '{"Name":"a","State":"running"}\n{"Name":"b","State":"exited"}'
    assert service._parse_ps_status(js) == "partial"


def test_parse_ps_status_stopped_when_empty() -> None:
    assert service._parse_ps_status("") == "stopped"


def _tpl() -> ComposeTemplate:
    return ComposeTemplate(
        id="browserless", name="B", version="1",
        compose_content='services:\n  b:\n    image: x:1\n    ports: ["${PORT}:3000"]',
        parameters=[ComposeParam(key="PORT", label="Port", type="port", required=True)],
        source="user",
    )


@pytest.mark.asyncio
async def test_deploy_happy_path(monkeypatch) -> None:
    host = SimpleNamespace(name="n1", type="ssh", address="root@x", host_cert_slug="s")
    monkeypatch.setattr(service, "_host_for_node", lambda node_id: host)
    monkeypatch.setattr(service, "check_ports", AsyncMock())
    monkeypatch.setattr(service, "resolve_env_values", lambda login, ns, ev: ev)
    monkeypatch.setattr(service, "write_host_file", AsyncMock())
    monkeypatch.setattr(service, "run_host_command", AsyncMock(return_value=(0, "up done", "")))
    monkeypatch.setattr(service, "create_deployment", AsyncMock())
    monkeypatch.setattr(service, "persist_op_log", AsyncMock())

    dep = await service.deploy(
        None, deployment_id="dep1", template=_tpl(), node_id="n1",
        owner_login="alice", secret_ns="ns", env_values={"PORT": "3000"},
    )
    assert dep.host_ports == [3000]
    assert dep.owner_login == "alice"
    service.check_ports.assert_awaited_once()
    assert service.write_host_file.await_count == 2  # compose + .env


def test_remote_dir_is_relative() -> None:
    rdir = service._remote_dir("dep1")
    assert not rdir.startswith(("~", "/"))
    assert rdir == "devpod-compose/dep1"


@pytest.mark.asyncio
async def test_deploy_failure_sets_error_and_raises(monkeypatch) -> None:
    host = SimpleNamespace(name="n1", type="ssh", address="root@x", host_cert_slug="s")
    monkeypatch.setattr(service, "_host_for_node", lambda node_id: host)
    monkeypatch.setattr(service, "check_ports", AsyncMock())
    monkeypatch.setattr(service, "resolve_env_values", lambda login, ns, ev: ev)
    monkeypatch.setattr(service, "write_host_file", AsyncMock())
    monkeypatch.setattr(service, "run_host_command", AsyncMock(return_value=(1, "", "boom")))
    monkeypatch.setattr(service, "create_deployment", AsyncMock())
    monkeypatch.setattr(service, "persist_op_log", AsyncMock())

    with pytest.raises(service.ComposeServiceError):
        await service.deploy(
            None, deployment_id="dep1", template=_tpl(), node_id="n1",
            owner_login="alice", secret_ns="ns", env_values={"PORT": "3000"},
        )

    service.create_deployment.assert_awaited_once()
    deployed = service.create_deployment.await_args[0][1]
    assert deployed.status == "error"
    service.persist_op_log.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifecycle_restart(monkeypatch) -> None:
    host = SimpleNamespace(name="n1", type="ssh", address="root@x", host_cert_slug="s")
    dep = SimpleNamespace(node_id="n1")
    monkeypatch.setattr(service, "_host_for_node", lambda node_id: host)
    monkeypatch.setattr(service, "get_deployment", AsyncMock(return_value=dep))
    monkeypatch.setattr(service, "run_host_command", AsyncMock(return_value=(0, "", "")))
    monkeypatch.setattr(service, "persist_op_log", AsyncMock())
    monkeypatch.setattr(service, "update_deployment_status", AsyncMock())
    monkeypatch.setattr(service, "refresh_status", AsyncMock(return_value="running"))

    await service.lifecycle(None, "dep1", "restart")

    cmd = service.run_host_command.await_args[0][1]
    assert "restart" in cmd
