from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_up_rejects_non_dns_safe_name(
    tmp_data_root: Path, global_cfg, fake_devpod_bin: list[str]
) -> None:
    """up() rejette un ws name non DNS-safe avant tout lancement."""
    from portal.devpod.service import DevPodService

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    # WorkspaceSpec.name est validé par pydantic — on teste via _ws_id directement
    with pytest.raises(ValueError, match="DNS"):
        svc._ws_id("alice", "INVALID NAME!")


# ---------------------------------------------------------------------------
# Bug 040 : _WS_ID_RE partagée entre devpod/service.py et exposure/__init__.py —
# tout ws_id accepté par _ws_id() doit l'être aussi par ExposureService.expose().
# ---------------------------------------------------------------------------


def test_ws_id_regex_is_the_same_object_in_service_and_exposure() -> None:
    """Une seule définition, importée des deux côtés — pas de risque de dérive."""
    from portal.devpod.service import _WS_ID_RE as service_re
    from portal.exposure import _WS_ID_RE as exposure_re

    assert service_re is exposure_re


@pytest.mark.asyncio
async def test_ws_id_rejects_combo_too_long_for_dns_label(
    tmp_data_root: Path, global_cfg, fake_devpod_bin: list[str]
) -> None:
    """login (40 chars max) + name (32 chars max) peut atteindre 73 caractères
    bruts, mais le sous-domaine Caddy réel est "ws-{ws_id}" — un label DNS est
    limité à 63 caractères. _ws_id() doit rejeter ce cas tôt, plutôt que de
    laisser expose() échouer après coup (statut running sans URL)."""
    from portal.devpod.service import DevPodService

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    login = "a" * 40
    name = "b" * 32
    with pytest.raises(ValueError, match="DNS"):
        svc._ws_id(login, name)


@pytest.mark.asyncio
async def test_ws_id_within_dns_limit_accepted_by_both_service_and_exposure(
    tmp_data_root: Path, global_cfg, fake_devpod_bin: list[str]
) -> None:
    """Un ws_id qui passe _ws_id() doit toujours être accepté par expose()."""
    from portal.devpod.service import DevPodService
    from portal.exposure import _WS_ID_RE as exposure_re

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    login = "a" * 20
    name = "b" * 32
    ws_id = svc._ws_id(login, name)
    assert exposure_re.fullmatch(ws_id)


@pytest.mark.asyncio
async def test_ws_id_with_dotted_login_accepted_by_both(
    tmp_data_root: Path, global_cfg, fake_devpod_bin: list[str]
) -> None:
    """Un login LDAP avec point (ex. "a.b") doit passer les deux regex — l'ancienne
    regex de service.py rejetait tout point (bug 040)."""
    from portal.devpod.service import DevPodService
    from portal.exposure import _WS_ID_RE as exposure_re

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    ws_id = svc._ws_id("a.b", "app")
    assert ws_id == "a.b-app"
    assert exposure_re.fullmatch(ws_id)


@pytest.mark.asyncio
async def test_up_writes_status_file(
    tmp_data_root: Path, global_cfg, fake_devpod_bin: list[str]
) -> None:
    """up() écrit un fichier de statut dans routes/<ws_id>.json."""
    from portal.auth.router import provision_user
    from portal.config.models import WorkspaceSpec
    from portal.devpod.service import DevPodService

    await provision_user(login="alice", sub="sub", data_root=tmp_data_root)

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    ws = WorkspaceSpec(name="myapp", source="git@github.com:user/repo.git")

    ws_id = await svc.up(login="alice", ws_spec=ws)
    assert ws_id == "alice-myapp"

    # Vérifier le statut provisioning immédiat (avant que la tâche de fond finisse)
    status_path = tmp_data_root / "routes" / f"{ws_id}.json"
    assert status_path.exists()
    immediate_data = json.loads(status_path.read_text(encoding="utf-8"))
    assert immediate_data["status"] == "provisioning"

    # Attendre que la tâche de fond passe de "provisioning" à "running"/"failed"
    # On sonde jusqu'à 10s pour absorber l'overhead subprocess Windows.
    for _ in range(50):
        await asyncio.sleep(0.2)
        if status_path.exists():
            data = json.loads(status_path.read_text(encoding="utf-8"))
            if data.get("status") in ("running", "failed"):
                break
    else:
        pytest.fail(f"Status file never reached running/failed (last: {status_path.read_text()})")

    assert status_path.exists(), f"Status file not found: {status_path}"
    data = json.loads(status_path.read_text(encoding="utf-8"))
    assert data["ws_id"] == ws_id
    assert data["status"] in ("running", "failed")


@pytest.mark.asyncio
async def test_secrets_not_leaked_in_logs(
    tmp_data_root: Path, global_cfg, fake_devpod_bin: list[str]
) -> None:
    """Les env vars passées à up() ne doivent pas apparaître dans les logs."""
    from portal.auth.router import provision_user
    from portal.config.models import WorkspaceSpec
    from portal.devpod.service import DevPodService

    await provision_user(login="alice", sub="sub", data_root=tmp_data_root)

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    ws = WorkspaceSpec(
        name="myapp",
        source="git@github.com:user/repo.git",
        env={"API_KEY": "SUPER_SECRET_VALUE"},
    )

    ws_id = await svc.up(login="alice", ws_spec=ws)

    # Attendre que la tâche de fond termine avant de vérifier les logs
    status_path = tmp_data_root / "routes" / f"{ws_id}.json"
    for _ in range(50):
        await asyncio.sleep(0.2)
        if status_path.exists():
            data = json.loads(status_path.read_text(encoding="utf-8"))
            if data.get("status") in ("running", "failed"):
                break

    log_path = tmp_data_root / "logs" / "alice" / f"{ws_id}.log"
    if log_path.exists():
        content = log_path.read_text(encoding="utf-8")
        assert "SUPER_SECRET_VALUE" not in content, "Secret leaked in logs!"


@pytest.mark.asyncio
async def test_status_returns_current_status(
    tmp_data_root: Path, global_cfg, fake_devpod_bin: list[str]
) -> None:
    """status() lit le fichier de statut et retourne l'état courant."""
    from portal.auth.router import provision_user
    from portal.devpod.service import DevPodService

    await provision_user(login="alice", sub="sub", data_root=tmp_data_root)

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    ws_id = "alice-myapp"

    routes_dir = tmp_data_root / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    (routes_dir / f"{ws_id}.json").write_text(
        json.dumps({"ws_id": ws_id, "status": "running"}), encoding="utf-8"
    )

    status = await svc.status(login="alice", ws_id=ws_id)
    assert status["status"] == "running"


@pytest.mark.asyncio
async def test_up_with_generate_ssh_key_creates_key(
    tmp_data_root: Path, global_cfg, fake_devpod_bin: list[str]
) -> None:
    """up(generate_ssh_key=True) crée la paire de clés avant de lancer devpod."""
    from portal.auth.router import provision_user
    from portal.config.models import WorkspaceSpec
    from portal.devpod.service import DevPodService

    await provision_user(login="alice", sub="sub", data_root=tmp_data_root)

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    ws = WorkspaceSpec(name="myapp", source="git@github.com:user/repo.git")

    ws_id = await svc.up(login="alice", ws_spec=ws, generate_ssh_key=True)

    pub_path = (
        tmp_data_root / "users" / "alice" / "keys" / "workspaces" / "myapp" / "id_ed25519.pub"
    )
    assert pub_path.exists()
    assert pub_path.read_text(encoding="utf-8").strip().startswith("ssh-ed25519 ")

    # Attendre que la tâche de fond se termine pour éviter que pytest-asyncio
    # ne reste bloqué à annuler une tâche avec un subprocess actif.
    status_path = tmp_data_root / "routes" / f"{ws_id}.json"
    for _ in range(50):
        await asyncio.sleep(0.2)
        if status_path.exists():
            data = json.loads(status_path.read_text(encoding="utf-8"))
            if data.get("status") in ("running", "failed"):
                break


@pytest.mark.asyncio
async def test_list_workspaces_isolates_by_login(
    tmp_data_root: Path, global_cfg, fake_devpod_bin: list[str]
) -> None:
    """list_workspaces ne retourne que les workspaces du user demandé."""
    from portal.devpod.service import DevPodService

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    routes_dir = tmp_data_root / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)

    # Écrire des statuts pour deux users différents
    (routes_dir / "alice-myapp.json").write_text(
        json.dumps({"ws_id": "alice-myapp", "login": "alice", "status": "running"}),
        encoding="utf-8",
    )
    (routes_dir / "bob-myapp.json").write_text(
        json.dumps({"ws_id": "bob-myapp", "login": "bob", "status": "running"}),
        encoding="utf-8",
    )

    alice_workspaces = await svc.list_workspaces(login="alice")
    assert len(alice_workspaces) == 1
    assert alice_workspaces[0]["ws_id"] == "alice-myapp"

    bob_workspaces = await svc.list_workspaces(login="bob")
    assert len(bob_workspaces) == 1
    assert bob_workspaces[0]["ws_id"] == "bob-myapp"


@pytest.mark.asyncio
async def test_up_docker_tls_passes_profile_to_write_devcontainer(
    tmp_data_root: Path, global_cfg, fake_devpod_bin: list[str]
) -> None:
    """up() transmet le profil à _write_devcontainer sur docker-tls."""
    import asyncio
    import json
    from unittest.mock import patch

    from portal.auth.router import provision_user
    from portal.config.models import WorkspaceSpec
    from portal.devpod.service import DevPodService
    from portal.profiles.models import Profile

    await provision_user(login="alice", sub="sub", data_root=tmp_data_root)

    profile = Profile(
        slug="py",
        scope="user",
        name="Python Dev",
        extensions=["ms-python.python"],
        settings={},
    )
    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    ws = WorkspaceSpec(name="myapp", source="github.com/org/repo")

    captured: list[Profile | None] = []
    original = svc._write_devcontainer

    def spy(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs.get("profile"))
        return original(*args, **kwargs)

    with patch.object(svc, "_write_devcontainer", side_effect=spy):
        ws_id = await svc.up(login="alice", ws_spec=ws, profile=profile)

    assert len(captured) == 1
    assert captured[0] is profile

    # Attendre la fin de la tâche de fond
    status_path = tmp_data_root / "routes" / f"{ws_id}.json"
    for _ in range(50):
        await asyncio.sleep(0.2)
        if status_path.exists():
            data = json.loads(status_path.read_text(encoding="utf-8"))
            if data.get("status") in ("running", "failed"):
                break


@pytest.mark.asyncio
async def test_up_raises_host_not_ready_when_no_cert_slug(
    tmp_data_root: Path, global_cfg
) -> None:
    """up() lève HostNotReadyError pour SSH host sans host_cert_slug."""
    from portal.config.models import HostConfig, WorkspaceSpec
    from portal.devpod.service import DevPodService, HostNotReadyError

    ssh_host = HostConfig(
        name="my-ssh-host",
        type="ssh",
        address="debian@10.0.0.1",
        host_cert_slug="",  # pas encore bootstrappé
    )
    mock_global = MagicMock()
    mock_global.hosts = [ssh_host]

    ws_spec = WorkspaceSpec(
        name="my-ws",
        source="https://github.com/org/repo",
        host="my-ssh-host",
    )

    svc = DevPodService.__new__(DevPodService)

    with (
        patch("portal.devpod.service.load_global", return_value=mock_global),
        pytest.raises(HostNotReadyError, match="clé SSH"),
    ):
        await svc.up(login="alice", ws_spec=ws_spec)


@pytest.mark.asyncio
async def test_up_propagates_real_error_when_cert_materialization_fails(
    tmp_data_root: Path,
) -> None:
    """Un échec AVANT l'init des variables de nettoyage ne doit pas être masqué.

    Régression du 2026-08-04 : `git_cred_home` était initialisée à l'intérieur du
    `try`, après plusieurs `await` faillibles. Quand l'un d'eux levait (ici la
    matérialisation du cert système du host), le `finally` la lisait non liée et
    levait un UnboundLocalError qui REMPLAÇAIT l'erreur réelle — toutes les
    reconnexions échouaient avec un message inexploitable.
    """
    from portal.config.models import HostConfig, WorkspaceSpec
    from portal.devpod.service import DevPodService

    ssh_host = HostConfig(
        name="my-ssh-host",
        type="ssh",
        address="debian@10.0.0.1",
        host_cert_slug="host.my-ssh-host.cert",
    )
    mock_global = MagicMock()
    mock_global.hosts = [ssh_host]

    ws_spec = WorkspaceSpec(
        name="my-ws", source="https://github.com/org/repo", host="my-ssh-host"
    )
    svc = DevPodService.__new__(DevPodService)

    async def _boom(slug: str, login: str = "") -> str:
        raise KeyError(f"System cert {slug!r} not found")

    with (
        patch("portal.devpod.service.load_global", return_value=mock_global),
        patch("portal.devpod.service.build_env", return_value={}),
        patch("portal.devpod.service._materialize_system_cert", side_effect=_boom),
        pytest.raises(KeyError, match="not found"),  # PAS un UnboundLocalError
    ):
        await svc.up(login="alice", ws_spec=ws_spec)


@pytest.mark.asyncio
async def test_up_propagates_real_error_when_provider_fails(tmp_data_root: Path) -> None:
    """Même garantie pour un échec plus tardif (provider), sur un host docker-tls
    sans credential git configuré — le chemin exact du reconnect."""
    from portal.config.models import HostConfig, WorkspaceSpec
    from portal.devpod.service import DevPodService

    host = HostConfig(name="node1", type="docker-tls", docker_host="tcp://10.0.0.2:2376")
    mock_global = MagicMock()
    mock_global.hosts = [host]

    ws_spec = WorkspaceSpec(
        name="my-ws", source="https://github.com/org/repo", host="node1", git_credential=""
    )
    svc = DevPodService.__new__(DevPodService)
    svc._exposure = None
    svc._devpod_bin = ["devpod"]

    async def _boom(**kwargs: object) -> str:
        raise RuntimeError("provider indisponible")

    with (
        patch("portal.devpod.service.load_global", return_value=mock_global),
        patch("portal.devpod.service.build_env", return_value={}),
        patch("portal.devpod.service.ensure_provider", side_effect=_boom),
        pytest.raises(RuntimeError, match="provider indisponible"),
    ):
        await svc.up(login="alice", ws_spec=ws_spec)
