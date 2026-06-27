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
