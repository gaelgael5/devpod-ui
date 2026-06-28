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
    assert service.write_host_file.await_count == 3  # compose + .env + override


def test_remote_dir_is_relative() -> None:
    rdir = service._remote_dir("dep1")
    assert not rdir.startswith(("~", "/"))
    assert rdir == "devpod-compose/dep1"


@pytest.mark.asyncio
async def test_deploy_failure_records_error(monkeypatch) -> None:
    """rc≠0 → row persistée status=error, retour normal (pas d'exception)."""
    host = SimpleNamespace(name="n1", type="ssh", address="root@x", host_cert_slug="s")
    monkeypatch.setattr(service, "_host_for_node", lambda node_id: host)
    monkeypatch.setattr(service, "check_ports", AsyncMock())
    monkeypatch.setattr(service, "resolve_env_values", lambda login, ns, ev: ev)
    monkeypatch.setattr(service, "write_host_file", AsyncMock())
    monkeypatch.setattr(service, "run_host_command", AsyncMock(return_value=(1, "", "boom")))
    monkeypatch.setattr(service, "create_deployment", AsyncMock())
    monkeypatch.setattr(service, "persist_op_log", AsyncMock())

    dep = await service.deploy(
        None, deployment_id="dep1", template=_tpl(), node_id="n1",
        owner_login="alice", secret_ns="ns", env_values={"PORT": "3000"},
    )

    assert dep.status == "error"
    service.create_deployment.assert_awaited_once()
    deployed = service.create_deployment.await_args[0][1]
    assert deployed.status == "error"
    service.persist_op_log.assert_awaited_once()


@pytest.mark.asyncio
async def test_deploy_rejects_plaintext_secret(monkeypatch) -> None:
    """Un param type:secret avec une valeur en clair doit lever ComposeServiceError."""
    from types import SimpleNamespace
    host = SimpleNamespace(name="n1", type="ssh", address="root@x", host_cert_slug="s")
    tpl = ComposeTemplate(
        id="svc", name="S", version="1",
        compose_content="services:\n  s:\n    image: x:1",
        parameters=[ComposeParam(key="TOK", label="Token", type="secret", required=True)],
        source="user",
    )
    monkeypatch.setattr(service, "_host_for_node", lambda node_id: host)
    monkeypatch.setattr(service, "check_ports", AsyncMock())

    with pytest.raises(service.ComposeServiceError, match="valeur en clair refusée"):
        await service.deploy(
            None, deployment_id="dep1", template=tpl, node_id="n1",
            owner_login="alice", secret_ns="ns", env_values={"TOK": "plaintext"},
        )


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


@pytest.mark.asyncio
async def test_lifecycle_failure_records_error(monkeypatch) -> None:
    """rc≠0 → statut mis à 'error' et retour normal (pas d'exception)."""
    host = SimpleNamespace(name="n1", type="ssh", address="root@x", host_cert_slug="s")
    dep = SimpleNamespace(node_id="n1")
    monkeypatch.setattr(service, "_host_for_node", lambda node_id: host)
    monkeypatch.setattr(service, "get_deployment", AsyncMock(return_value=dep))
    monkeypatch.setattr(service, "run_host_command", AsyncMock(return_value=(1, "", "boom")))
    monkeypatch.setattr(service, "persist_op_log", AsyncMock())
    monkeypatch.setattr(service, "update_deployment_status", AsyncMock())

    await service.lifecycle(None, "dep1", "restart")  # ne doit pas lever

    service.update_deployment_status.assert_awaited_once()
    args = service.update_deployment_status.await_args
    assert args[0][2] == "error"  # positional: (conn, deployment_id, status, ...)
    service.persist_op_log.assert_awaited_once()


# ---------------------------------------------------------------------------
# Mode alias (chromium>3000:3000) — auto-allocation de ports
# ---------------------------------------------------------------------------

def _alias_tpl() -> ComposeTemplate:
    return ComposeTemplate(
        id="chromium", name="Chromium", version="1",
        compose_content=(
            "services:\n"
            "  browser:\n"
            "    image: chromium:1.0.0\n"
            "    ports:\n"
            "      - chromium>3000:3000\n"
        ),
        parameters=[],
        source="user",
    )


@pytest.mark.asyncio
async def test_deploy_alias_mode_allocates_ports(monkeypatch) -> None:
    """Le mode alias appelle allocate_ports, pas check_ports."""
    host = SimpleNamespace(name="n1", type="ssh", address="root@x", host_cert_slug="s")
    monkeypatch.setattr(service, "_host_for_node", lambda node_id: host)
    monkeypatch.setattr(
        service, "allocate_ports", AsyncMock(return_value={"chromium": 3005})
    )
    monkeypatch.setattr(service, "check_ports", AsyncMock())
    monkeypatch.setattr(service, "resolve_env_values", lambda login, ns, ev: ev)
    monkeypatch.setattr(service, "write_host_file", AsyncMock())
    monkeypatch.setattr(service, "run_host_command", AsyncMock(return_value=(0, "up done", "")))
    monkeypatch.setattr(service, "create_deployment", AsyncMock())
    monkeypatch.setattr(service, "persist_op_log", AsyncMock())

    dep = await service.deploy(
        None, deployment_id="dep2", template=_alias_tpl(), node_id="n1",
        owner_login="alice", secret_ns="ns", env_values={},
    )

    service.allocate_ports.assert_awaited_once()
    service.check_ports.assert_not_awaited()
    assert dep.host_ports == [3005]


@pytest.mark.asyncio
async def test_deploy_alias_mode_rewrites_yaml(monkeypatch) -> None:
    """Le YAML écrit sur le nœud a le port résolu (3005:3000), pas l'alias."""
    host = SimpleNamespace(name="n1", type="ssh", address="root@x", host_cert_slug="s")
    monkeypatch.setattr(service, "_host_for_node", lambda node_id: host)
    monkeypatch.setattr(
        service, "allocate_ports", AsyncMock(return_value={"chromium": 3005})
    )
    monkeypatch.setattr(service, "resolve_env_values", lambda login, ns, ev: ev)
    written_files: dict[str, str] = {}

    async def capture_write(host, path, content):
        written_files[path] = content

    monkeypatch.setattr(service, "write_host_file", capture_write)
    monkeypatch.setattr(service, "run_host_command", AsyncMock(return_value=(0, "", "")))
    monkeypatch.setattr(service, "create_deployment", AsyncMock())
    monkeypatch.setattr(service, "persist_op_log", AsyncMock())

    await service.deploy(
        None, deployment_id="dep3", template=_alias_tpl(), node_id="n1",
        owner_login="alice", secret_ns="ns", env_values={},
    )

    compose_content = written_files["devpod-compose/dep3/docker-compose.yml"]
    assert "3005:3000" in compose_content
    assert "chromium>" not in compose_content

    assert "devpod-compose/dep3/docker-compose.override.yml" in written_files
    override_content = written_files["devpod-compose/dep3/docker-compose.override.yml"]
    assert "io.yoops.portal.deployment_id" in override_content


@pytest.mark.asyncio
async def test_deploy_classic_mode_writes_override(monkeypatch) -> None:
    """Même en mode classique (param type=port), l'override avec labels est écrit."""
    host = SimpleNamespace(name="n1", type="ssh", address="root@x", host_cert_slug="s")
    monkeypatch.setattr(service, "_host_for_node", lambda node_id: host)
    monkeypatch.setattr(service, "check_ports", AsyncMock())
    monkeypatch.setattr(service, "resolve_env_values", lambda login, ns, ev: ev)
    written_files: dict[str, str] = {}

    async def capture_write(host, path, content):
        written_files[path] = content

    monkeypatch.setattr(service, "write_host_file", capture_write)
    monkeypatch.setattr(service, "run_host_command", AsyncMock(return_value=(0, "", "")))
    monkeypatch.setattr(service, "create_deployment", AsyncMock())
    monkeypatch.setattr(service, "persist_op_log", AsyncMock())

    await service.deploy(
        None, deployment_id="dep4", template=_tpl(), node_id="n1",
        owner_login="alice", secret_ns="ns", env_values={"PORT": "3000"},
    )

    assert "devpod-compose/dep4/docker-compose.override.yml" in written_files
    override = written_files["devpod-compose/dep4/docker-compose.override.yml"]
    assert "io.yoops.portal.owner" in override
    assert "alice" in override
