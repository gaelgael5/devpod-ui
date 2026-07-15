"""Tests du service lifecycle compose (spec 26 §5)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from portal.compose import service
from portal.compose.models import ComposeAutoStart, ComposeParam, ComposeTemplate
from portal.compose.ports import PortConflict
from portal.compose.service import ComposeServiceError
from portal.devpod.host_exec import HostExecError


class _FakeConn:
    async def __aenter__(self) -> "_FakeConn":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeEngine:
    def begin(self) -> _FakeConn:
        return _FakeConn()

    def connect(self) -> _FakeConn:
        return _FakeConn()


def _patch_deploy_db(monkeypatch) -> None:
    """Mocke la couche DB de deploy()/deploy_stream (réservation précoce, bug 015)."""
    monkeypatch.setattr(service, "_get_engine", lambda: _FakeEngine())
    monkeypatch.setattr(service, "acquire_node_ports_lock", AsyncMock())
    monkeypatch.setattr(service, "get_deployment_by_name_node", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "create_deployment", AsyncMock())
    monkeypatch.setattr(service, "update_deployment_status", AsyncMock())
    monkeypatch.setattr(service, "delete_deployment", AsyncMock())
    monkeypatch.setattr(service, "persist_op_log", AsyncMock())


def test_parse_ps_status_running() -> None:
    js = '{"Name":"a","State":"running"}\n{"Name":"b","State":"running"}'
    assert service._parse_ps_status(js) == "running"


def test_parse_ps_status_partial() -> None:
    js = '{"Name":"a","State":"running"}\n{"Name":"b","State":"exited"}'
    assert service._parse_ps_status(js) == "partial"


def test_parse_ps_status_stopped_when_empty() -> None:
    assert service._parse_ps_status("") == "stopped"


def test_parse_compose_ls_json_array() -> None:
    out = (
        '[{"Name":"chromium","Status":"running(1)","ConfigFiles":"/opt/a/docker-compose.yml"},'
        '{"Name":"alloy","Status":"running(1)","ConfigFiles":"/opt/b/compose.yml"}]'
    )
    stacks = service._parse_compose_ls(out)
    assert stacks == [
        {"name": "alloy", "status": "running(1)", "configFiles": "/opt/b/compose.yml"},
        {"name": "chromium", "status": "running(1)", "configFiles": "/opt/a/docker-compose.yml"},
    ]


def test_parse_compose_ls_json_lines() -> None:
    out = (
        '{"Name":"proj","Status":"exited(2)","ConfigFiles":"/x/docker-compose.yml"}\n'
        '\n'
        '{"Name":"","Status":"running"}\n'  # sans nom → ignoré
    )
    assert service._parse_compose_ls(out) == [
        {"name": "proj", "status": "exited(2)", "configFiles": "/x/docker-compose.yml"}
    ]


def test_parse_compose_ls_empty_and_garbage() -> None:
    assert service._parse_compose_ls("") == []
    assert service._parse_compose_ls("not json at all") == []


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
    _patch_deploy_db(monkeypatch)

    dep = await service.deploy(
        None, name="dep1", template=_tpl(), node_id="n1",
        owner_login="alice", secret_ns="ns", env_values={"PORT": "3000"},
    )
    assert dep.host_ports == [3000]
    assert dep.owner_login == "alice"
    assert dep.status == "running"
    service.check_ports.assert_awaited_once()
    assert service.write_host_file.await_count == 3  # compose + .env + override
    # Réservation précoce (bug 015) : ligne « created » AVANT le compose up…
    service.create_deployment.assert_awaited_once()
    reservation = service.create_deployment.await_args[0][1]
    assert reservation.status == "created"
    assert reservation.host_ports == [3000]
    # …finalisée en « running » après.
    service.update_deployment_status.assert_awaited_once()
    assert service.update_deployment_status.await_args[0][1:3] == (dep.uid, "running")


@pytest.mark.asyncio
async def test_deploy_reserves_ports_before_compose_up(monkeypatch) -> None:
    """Bug 015 : la ligne de réservation est commitée AVANT docker compose up —
    un déploiement concurrent voit les ports pris pendant toute la durée du up."""
    host = SimpleNamespace(name="n1", type="ssh", address="root@x", host_cert_slug="s")
    events: list[str] = []

    async def fake_create(conn, dep) -> None:
        events.append("reserve")

    async def fake_run(host, cmd, timeout) -> tuple[int, str, str]:
        events.append("compose_up")
        return (0, "", "")

    monkeypatch.setattr(service, "_host_for_node", lambda node_id: host)
    monkeypatch.setattr(service, "check_ports", AsyncMock())
    monkeypatch.setattr(service, "resolve_env_values", lambda login, ns, ev: ev)
    monkeypatch.setattr(service, "write_host_file", AsyncMock())
    monkeypatch.setattr(service, "run_host_command", fake_run)
    _patch_deploy_db(monkeypatch)
    monkeypatch.setattr(service, "create_deployment", fake_create)

    await service.deploy(
        None, name="dep1", template=_tpl(), node_id="n1",
        owner_login="alice", secret_ns="ns", env_values={"PORT": "3000"},
    )
    assert events == ["reserve", "compose_up"]


@pytest.mark.asyncio
async def test_deploy_removes_reservation_on_exec_error(monkeypatch) -> None:
    """Échec d'exécution SSH : la réservation est retirée (état final = aucune
    ligne, comme avant) et ComposeServiceError est propagée."""
    host = SimpleNamespace(name="n1", type="ssh", address="root@x", host_cert_slug="s")
    monkeypatch.setattr(service, "_host_for_node", lambda node_id: host)
    monkeypatch.setattr(service, "check_ports", AsyncMock())
    monkeypatch.setattr(service, "resolve_env_values", lambda login, ns, ev: ev)
    monkeypatch.setattr(service, "write_host_file", AsyncMock(side_effect=HostExecError("ssh KO")))
    _patch_deploy_db(monkeypatch)

    with pytest.raises(ComposeServiceError):
        await service.deploy(
            None, name="dep1", template=_tpl(), node_id="n1",
            owner_login="alice", secret_ns="ns", env_values={"PORT": "3000"},
        )

    service.create_deployment.assert_awaited_once()
    reservation = service.create_deployment.await_args[0][1]
    service.delete_deployment.assert_awaited_once()
    assert service.delete_deployment.await_args[0][1] == reservation.uid
    service.update_deployment_status.assert_not_awaited()


def test_remote_dir_is_relative() -> None:
    rdir = service._remote_dir("dep1")
    assert not rdir.startswith(("~", "/"))
    assert rdir == "devpod-compose/dep1"


@pytest.mark.asyncio
async def test_deploy_failure_records_error(monkeypatch) -> None:
    """rc≠0 → la réservation est finalisée en status=error, retour normal."""
    host = SimpleNamespace(name="n1", type="ssh", address="root@x", host_cert_slug="s")
    monkeypatch.setattr(service, "_host_for_node", lambda node_id: host)
    monkeypatch.setattr(service, "check_ports", AsyncMock())
    monkeypatch.setattr(service, "resolve_env_values", lambda login, ns, ev: ev)
    monkeypatch.setattr(service, "write_host_file", AsyncMock())
    monkeypatch.setattr(service, "run_host_command", AsyncMock(return_value=(1, "", "boom")))
    _patch_deploy_db(monkeypatch)

    dep = await service.deploy(
        None, name="dep1", template=_tpl(), node_id="n1",
        owner_login="alice", secret_ns="ns", env_values={"PORT": "3000"},
    )

    assert dep.status == "error"
    service.update_deployment_status.assert_awaited_once()
    assert service.update_deployment_status.await_args[0][1:3] == (dep.uid, "error")
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
            None, name="dep1", template=tpl, node_id="n1",
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
    _patch_deploy_db(monkeypatch)

    dep = await service.deploy(
        None, name="dep2", template=_alias_tpl(), node_id="n1",
        owner_login="alice", secret_ns="ns", env_values={},
    )

    service.allocate_ports.assert_awaited_once()
    service.check_ports.assert_not_awaited()
    assert dep.host_ports == [3005]
    reservation = service.create_deployment.await_args[0][1]
    assert reservation.host_ports == [3005]


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
    _patch_deploy_db(monkeypatch)

    await service.deploy(
        None, name="dep3", template=_alias_tpl(), node_id="n1",
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
    _patch_deploy_db(monkeypatch)

    await service.deploy(
        None, name="dep4", template=_tpl(), node_id="n1",
        owner_login="alice", secret_ns="ns", env_values={"PORT": "3000"},
    )

    assert "devpod-compose/dep4/docker-compose.override.yml" in written_files
    override = written_files["devpod-compose/dep4/docker-compose.override.yml"]
    assert "io.yoops.portal.owner" in override
    assert "alice" in override


# ---------------------------------------------------------------------------
# prepare_deployment / deploy_stream — réservation précoce (bug 015)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prepare_deployment_reserves_under_node_lock(monkeypatch) -> None:
    """L'allocation se fait sous verrou advisory et insère la ligne « created »."""
    host = SimpleNamespace(name="n1", type="ssh", address="root@x", host_cert_slug="s")
    monkeypatch.setattr(service, "_host_for_node", lambda node_id: host)
    monkeypatch.setattr(service, "allocate_ports", AsyncMock(return_value={"chromium": 3005}))
    _patch_deploy_db(monkeypatch)

    uid, port_map, host_ports, compose = await service.prepare_deployment(
        None, name="dep1", template=_alias_tpl(), node_id="n1",
        owner_login="alice", env_values={},
    )

    service.acquire_node_ports_lock.assert_awaited_once()
    assert host_ports == [3005]
    assert "3005:3000" in compose
    reservation = service.create_deployment.await_args[0][1]
    assert reservation.uid == uid
    assert reservation.status == "created"
    assert reservation.host_ports == [3005]


@pytest.mark.asyncio
async def test_prepare_deployment_rejects_duplicate_name(monkeypatch) -> None:
    """Re-vérification du nom SOUS le verrou : pas de réservation en double."""
    host = SimpleNamespace(name="n1", type="ssh", address="root@x", host_cert_slug="s")
    monkeypatch.setattr(service, "_host_for_node", lambda node_id: host)
    _patch_deploy_db(monkeypatch)
    monkeypatch.setattr(
        service, "get_deployment_by_name_node", AsyncMock(return_value=SimpleNamespace(uid="x"))
    )

    with pytest.raises(ComposeServiceError, match="existe déjà"):
        await service.prepare_deployment(
            None, name="dep1", template=_alias_tpl(), node_id="n1",
            owner_login="alice", env_values={},
        )
    service.create_deployment.assert_not_awaited()


@pytest.mark.asyncio
async def test_deploy_stream_finalizes_reservation(monkeypatch) -> None:
    """deploy_stream met à jour la ligne réservée (jamais d'INSERT tardif)."""
    host = SimpleNamespace(name="n1", type="ssh", address="root@x", host_cert_slug="s")
    monkeypatch.setattr(service, "_host_for_node", lambda node_id: host)
    monkeypatch.setattr(service, "resolve_env_values", lambda login, ns, ev: ev)
    monkeypatch.setattr(service, "write_host_file", AsyncMock())
    _patch_deploy_db(monkeypatch)

    async def fake_stream(host, cmd, timeout=600.0):
        yield "pull done"

    monkeypatch.setattr(service, "stream_host_command", fake_stream)

    lines = [
        line
        async for line in service.deploy_stream(
            uid="u1", name="dep1", template=_tpl(), node_id="n1",
            owner_login="alice", secret_ns="ns", env_values={"PORT": "3000"},
            port_map={}, host_ports=[3000], compose_to_write="services: {}",
        )
    ]

    assert any(line.startswith("__RESULT__:") for line in lines)
    service.create_deployment.assert_not_awaited()
    service.update_deployment_status.assert_awaited_once()
    assert service.update_deployment_status.await_args[0][1:3] == ("u1", "running")


@pytest.mark.asyncio
async def test_deploy_stream_removes_reservation_on_write_failure(monkeypatch) -> None:
    """Échec d'écriture des fichiers : la réservation est retirée avant de propager."""
    host = SimpleNamespace(name="n1", type="ssh", address="root@x", host_cert_slug="s")
    monkeypatch.setattr(service, "_host_for_node", lambda node_id: host)
    monkeypatch.setattr(service, "resolve_env_values", lambda login, ns, ev: ev)
    monkeypatch.setattr(service, "write_host_file", AsyncMock(side_effect=HostExecError("ssh KO")))
    _patch_deploy_db(monkeypatch)

    with pytest.raises(ComposeServiceError):
        async for _ in service.deploy_stream(
            uid="u1", name="dep1", template=_tpl(), node_id="n1",
            owner_login="alice", secret_ns="ns", env_values={"PORT": "3000"},
            port_map={}, host_ports=[3000], compose_to_write="services: {}",
        ):
            pass

    service.delete_deployment.assert_awaited_once()
    assert service.delete_deployment.await_args[0][1] == "u1"
    service.update_deployment_status.assert_not_awaited()


# ---------------------------------------------------------------------------
# deploy_auto_start_templates
# ---------------------------------------------------------------------------


def _auto_entry(template_id: str, env_values: dict[str, str] | None = None) -> ComposeAutoStart:
    return ComposeAutoStart(
        id=1, owner_login="alice", template_id=template_id, env_values=env_values or {}
    )


@pytest.mark.asyncio
async def test_deploy_auto_start_skips_when_no_entries(monkeypatch) -> None:
    monkeypatch.setattr(service, "list_auto_start_for_user", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "deploy", AsyncMock())

    lines = [
        line
        async for line in service.deploy_auto_start_templates(
            None, owner_login="alice", secret_ns="ns", node_id="n1"
        )
    ]
    assert lines == []
    service.deploy.assert_not_awaited()


@pytest.mark.asyncio
async def test_deploy_auto_start_skips_existing_deployment(monkeypatch) -> None:
    """Idempotence : ne rien faire si un déploiement existe déjà sur ce nœud."""
    monkeypatch.setattr(
        service,
        "list_auto_start_for_user",
        AsyncMock(return_value=[_auto_entry("alloy-collector")]),
    )
    monkeypatch.setattr(
        service, "get_deployment_by_name_node", AsyncMock(return_value=SimpleNamespace(uid="x"))
    )
    monkeypatch.setattr(service, "deploy", AsyncMock())

    lines = [
        line
        async for line in service.deploy_auto_start_templates(
            None, owner_login="alice", secret_ns="ns", node_id="n1"
        )
    ]
    assert lines == []
    service.deploy.assert_not_awaited()


@pytest.mark.asyncio
async def test_deploy_auto_start_deploys_missing_template(monkeypatch) -> None:
    tpl = _tpl()
    monkeypatch.setattr(
        service, "list_auto_start_for_user",
        AsyncMock(return_value=[_auto_entry(tpl.id, {"PORT": "3000"})]),
    )
    monkeypatch.setattr(service, "get_deployment_by_name_node", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "get_template", AsyncMock(return_value=tpl))
    monkeypatch.setattr(service, "deploy", AsyncMock())

    lines = [
        line
        async for line in service.deploy_auto_start_templates(
            None, owner_login="alice", secret_ns="ns", node_id="n1"
        )
    ]
    assert any("démarré" in line for line in lines)
    service.deploy.assert_awaited_once_with(
        None,
        name=tpl.id,
        template=tpl,
        node_id="n1",
        owner_login="alice",
        secret_ns="ns",
        env_values={"PORT": "3000"},
    )


@pytest.mark.asyncio
async def test_deploy_auto_start_one_failure_does_not_block_others(monkeypatch) -> None:
    """Best-effort : une entrée en échec n'empêche pas les suivantes."""
    tpl_a = ComposeTemplate(id="a", name="A", version="1", compose_content="services: {}")
    tpl_b = ComposeTemplate(id="b", name="B", version="1", compose_content="services: {}")
    monkeypatch.setattr(
        service, "list_auto_start_for_user",
        AsyncMock(return_value=[_auto_entry("a"), _auto_entry("b")]),
    )
    monkeypatch.setattr(service, "get_deployment_by_name_node", AsyncMock(return_value=None))

    async def fake_get_template(conn, template_id):
        return tpl_a if template_id == "a" else tpl_b

    monkeypatch.setattr(service, "get_template", fake_get_template)

    deploy_mock = AsyncMock(side_effect=[ComposeServiceError("boom"), None])
    monkeypatch.setattr(service, "deploy", deploy_mock)

    lines = [
        line
        async for line in service.deploy_auto_start_templates(
            None, owner_login="alice", secret_ns="ns", node_id="n1"
        )
    ]
    assert deploy_mock.await_count == 2
    assert any("AVERTISSEMENT" in line for line in lines)
    assert any("démarré" in line for line in lines)


@pytest.mark.asyncio
async def test_deploy_auto_start_survives_port_conflict(monkeypatch) -> None:
    tpl = _tpl()
    monkeypatch.setattr(
        service, "list_auto_start_for_user", AsyncMock(return_value=[_auto_entry(tpl.id)])
    )
    monkeypatch.setattr(service, "get_deployment_by_name_node", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "get_template", AsyncMock(return_value=tpl))
    monkeypatch.setattr(
        service, "deploy", AsyncMock(side_effect=PortConflict({3000}, 3001))
    )

    lines = [
        line
        async for line in service.deploy_auto_start_templates(
            None, owner_login="alice", secret_ns="ns", node_id="n1"
        )
    ]
    assert any("AVERTISSEMENT" in line for line in lines)
