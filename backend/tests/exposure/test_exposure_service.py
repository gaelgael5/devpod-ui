from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    (tmp_path / "routes").mkdir(parents=True)
    return tmp_path


def _make_exposure_service(data_root: Path, caddy_mock=None, registry_mock=None):
    """Fabrique un ExposureService avec CaddyClient et PortRegistry mockés."""
    from portal.exposure import ExposureService
    from portal.exposure.caddy import CaddyClient
    from portal.exposure.ports import PortRegistry

    caddy = caddy_mock or MagicMock(spec=CaddyClient)
    caddy.upsert_route = AsyncMock()
    caddy.remove_route = AsyncMock()

    registry = registry_mock or MagicMock(spec=PortRegistry)
    registry.allocate = AsyncMock(return_value=41000)

    return (
        ExposureService(
            caddy=caddy,
            registry=registry,
            data_root=data_root,
            base_domain="dev.yoops.org",
        ),
        caddy,
        registry,
    )


@pytest.mark.asyncio
async def test_expose_calls_caddy_upsert_route(data_root: Path) -> None:
    """expose() appelle caddy.upsert_route avec les bons paramètres."""
    svc, caddy, _ = _make_exposure_service(data_root)
    url = await svc.expose(ws_id="alice-myapp", node_ip="192.168.1.50", host_port=41000)
    caddy.upsert_route.assert_awaited_once_with(
        route_id="ws-alice-myapp",
        match_host="ws-alice-myapp.dev.yoops.org",
        upstream="192.168.1.50:41000",
    )
    assert url == "https://ws-alice-myapp.dev.yoops.org"


@pytest.mark.asyncio
async def test_expose_writes_hostname_and_url_to_routes_file(data_root: Path) -> None:
    """expose() écrit hostname et url dans routes/<ws_id>.json."""
    svc, _, _ = _make_exposure_service(data_root)
    await svc.expose(ws_id="alice-myapp", node_ip="192.168.1.50", host_port=41000)
    route_file = data_root / "routes" / "alice-myapp.json"
    assert route_file.exists()
    data = json.loads(route_file.read_text(encoding="utf-8"))
    assert data["hostname"] == "ws-alice-myapp.dev.yoops.org"
    assert data["url"] == "https://ws-alice-myapp.dev.yoops.org"


@pytest.mark.asyncio
async def test_expose_preserves_existing_fields(data_root: Path) -> None:
    """expose() ne supprime pas les champs existants dans routes/<ws_id>.json."""
    # Pré-remplir le fichier avec un status existant
    route_file = data_root / "routes" / "alice-myapp.json"
    route_file.write_text(
        json.dumps({"ws_id": "alice-myapp", "status": "running", "login": "alice"}),
        encoding="utf-8",
    )
    svc, _, _ = _make_exposure_service(data_root)
    await svc.expose(ws_id="alice-myapp", node_ip="192.168.1.50", host_port=41000)
    data = json.loads(route_file.read_text(encoding="utf-8"))
    assert data["status"] == "running"
    assert data["login"] == "alice"
    assert data["hostname"] == "ws-alice-myapp.dev.yoops.org"
    assert data["url"] == "https://ws-alice-myapp.dev.yoops.org"


@pytest.mark.asyncio
async def test_unexpose_calls_caddy_remove_route(data_root: Path) -> None:
    """unexpose() appelle caddy.remove_route avec le bon route_id."""
    svc, caddy, _ = _make_exposure_service(data_root)
    await svc.unexpose(ws_id="alice-myapp")
    caddy.remove_route.assert_awaited_once_with("ws-alice-myapp")


@pytest.mark.asyncio
async def test_unexpose_clears_hostname_and_url(data_root: Path) -> None:
    """unexpose() vide hostname et url dans routes/<ws_id>.json sans supprimer le fichier."""
    route_file = data_root / "routes" / "alice-myapp.json"
    route_file.write_text(
        json.dumps(
            {
                "ws_id": "alice-myapp",
                "status": "stopped",
                "login": "alice",
                "hostname": "ws-alice-myapp.dev.yoops.org",
                "url": "https://ws-alice-myapp.dev.yoops.org",
            }
        ),
        encoding="utf-8",
    )
    svc, _, _ = _make_exposure_service(data_root)
    await svc.unexpose(ws_id="alice-myapp")
    data = json.loads(route_file.read_text(encoding="utf-8"))
    assert data["hostname"] == ""
    assert data["url"] == ""
    assert data["status"] == "stopped"  # autres champs préservés


@pytest.mark.asyncio
async def test_unexpose_no_op_if_no_file(data_root: Path) -> None:
    """unexpose() ne lève pas d'exception si le fichier de route n'existe pas."""
    svc, caddy, _ = _make_exposure_service(data_root)
    # Pas d'exception attendue
    await svc.unexpose(ws_id="ghost-workspace")
    caddy.remove_route.assert_awaited_once_with("ws-ghost-workspace")


@pytest.mark.asyncio
async def test_allocate_port_delegates_to_registry(data_root: Path) -> None:
    """allocate_port() délègue à registry.allocate() et retourne le port."""
    svc, _, registry = _make_exposure_service(data_root)
    port = await svc.allocate_port("alice-myapp")
    assert port == 41000
    registry.allocate.assert_awaited_once_with("alice-myapp")


@pytest.mark.asyncio
async def test_expose_rejects_path_traversal_ws_id(data_root: Path) -> None:
    """expose() rejette un ws_id contenant un path traversal."""
    svc, _, _ = _make_exposure_service(data_root)
    with pytest.raises(ValueError):
        await svc.expose(ws_id="../secret", node_ip="192.168.1.50", host_port=41000)
