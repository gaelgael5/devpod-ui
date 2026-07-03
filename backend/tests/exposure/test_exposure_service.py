from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_exposure_service(caddy_mock=None, registry_mock=None):
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
            base_domain="dev.yoops.org",
        ),
        caddy,
        registry,
    )


@pytest.mark.asyncio
async def test_expose_calls_caddy_upsert_route(db_engine) -> None:
    """expose() appelle caddy.upsert_route avec les bons paramètres."""
    svc, caddy, _ = _make_exposure_service()
    url = await svc.expose(ws_id="alice-myapp", node_ip="192.168.1.50", host_port=41000)
    caddy.upsert_route.assert_awaited_once_with(
        route_id="ws-alice-myapp",
        match_host="ws-alice-myapp.dev.yoops.org",
        upstream="192.168.1.50:41000",
    )
    assert url == "https://ws-alice-myapp.dev.yoops.org/?folder=/workspaces/alice-myapp"


@pytest.mark.asyncio
async def test_expose_writes_hostname_and_url_to_db(db_engine) -> None:
    """expose() écrit hostname et url en DB (workspace_status)."""
    from portal.db.engine import _get_engine
    from portal.db.workspace_status import get_status_db

    svc, _, _ = _make_exposure_service()
    await svc.expose(ws_id="alice-myapp", node_ip="192.168.1.50", host_port=41000)

    async with _get_engine().connect() as conn:
        row = await get_status_db("alice-myapp", conn)
    assert row is not None
    assert row["hostname"] == "ws-alice-myapp.dev.yoops.org"
    assert row["url"] == "https://ws-alice-myapp.dev.yoops.org/?folder=/workspaces/alice-myapp"


@pytest.mark.asyncio
async def test_expose_preserves_existing_fields(db_engine) -> None:
    """expose() ne supprime pas les champs existants dans workspace_status."""
    from portal.db.engine import _get_engine
    from portal.db.workspace_status import get_status_db, upsert_status_db

    async with _get_engine().begin() as conn:
        await upsert_status_db("alice-myapp", "running", conn, login="alice")

    svc, _, _ = _make_exposure_service()
    await svc.expose(ws_id="alice-myapp", node_ip="192.168.1.50", host_port=41000)

    async with _get_engine().connect() as conn:
        row = await get_status_db("alice-myapp", conn)
    assert row is not None
    assert row["status"] == "running"
    assert row["login"] == "alice"
    assert row["hostname"] == "ws-alice-myapp.dev.yoops.org"


@pytest.mark.asyncio
async def test_unexpose_calls_caddy_remove_route(db_engine) -> None:
    """unexpose() appelle caddy.remove_route avec le bon route_id."""
    svc, caddy, _ = _make_exposure_service()
    await svc.unexpose(ws_id="alice-myapp")
    caddy.remove_route.assert_awaited_once_with("ws-alice-myapp")


@pytest.mark.asyncio
async def test_unexpose_clears_hostname_and_url(db_engine) -> None:
    """unexpose() vide hostname et url dans workspace_status sans supprimer la ligne."""
    from portal.db.engine import _get_engine
    from portal.db.workspace_status import get_status_db, upsert_status_db

    async with _get_engine().begin() as conn:
        await upsert_status_db(
            "alice-myapp",
            "stopped",
            conn,
            login="alice",
            hostname="ws-alice-myapp.dev.yoops.org",
            url="https://ws-alice-myapp.dev.yoops.org",
        )

    svc, _, _ = _make_exposure_service()
    await svc.unexpose(ws_id="alice-myapp")

    async with _get_engine().connect() as conn:
        row = await get_status_db("alice-myapp", conn)
    assert row is not None
    assert row["hostname"] is None
    assert row["url"] is None
    assert row["status"] == "stopped"


@pytest.mark.asyncio
async def test_unexpose_no_op_if_not_in_db(db_engine) -> None:
    """unexpose() ne lève pas d'exception si le ws_id n'est pas en DB."""
    svc, caddy, _ = _make_exposure_service()
    await svc.unexpose(ws_id="ghost-workspace")
    caddy.remove_route.assert_awaited_once_with("ws-ghost-workspace")


@pytest.mark.asyncio
async def test_allocate_port_delegates_to_registry(db_engine) -> None:
    """allocate_port() délègue à registry.allocate() et retourne le port."""
    svc, _, registry = _make_exposure_service()
    port = await svc.allocate_port("alice-myapp")
    assert port == 41000
    registry.allocate.assert_awaited_once_with("alice-myapp")


@pytest.mark.asyncio
async def test_expose_rejects_path_traversal_ws_id(db_engine) -> None:
    """expose() rejette un ws_id contenant un path traversal."""
    svc, _, _ = _make_exposure_service()
    with pytest.raises(ValueError):
        await svc.expose(ws_id="../secret", node_ip="192.168.1.50", host_port=41000)


def _direct_service(workspace_host: str, local_domain: str, *, dev_mode: bool):
    """ExposureService en fallback URL directe (dev_mode ou base_domain vide).

    L'écriture DB est débranchée : ces tests ne portent que sur la construction
    de l'URL (résolution DHCP de workspace_host), pas sur la persistance.
    """
    from portal.exposure import ExposureService
    from portal.exposure.ports import PortRegistry

    registry = MagicMock(spec=PortRegistry)
    registry.allocate = AsyncMock(return_value=41000)
    svc = ExposureService(
        registry=registry,
        base_domain="",
        caddy=None,
        url_scheme="http",
        dev_mode=dev_mode,
        workspace_host=workspace_host,
        local_domain=local_domain,
    )
    svc._write_exposure = AsyncMock()  # type: ignore[method-assign]
    return svc


@pytest.mark.asyncio
async def test_dev_mode_resolves_hostname_workspace_host(monkeypatch) -> None:
    """En dev, un workspace_host hostname est re-résolu en IP courante (DHCP)."""
    import portal.exposure as exposure_mod

    resolve = AsyncMock(return_value="192.168.10.42")
    monkeypatch.setattr(exposure_mod, "resolve_ipv4", resolve)

    svc = _direct_service("portal", "home.lan", dev_mode=True)
    url = await svc.expose(ws_id="alice-myapp", node_ip="portal", host_port=41000)

    resolve.assert_awaited_once_with("portal.home.lan")
    assert url == "http://192.168.10.42:41000/?folder=/workspaces/alice-myapp"


@pytest.mark.asyncio
async def test_dev_mode_ip_literal_not_resolved(monkeypatch) -> None:
    """Une IP littérale dans workspace_host n'est jamais résolue."""
    import portal.exposure as exposure_mod

    resolve = AsyncMock(return_value="1.1.1.1")
    monkeypatch.setattr(exposure_mod, "resolve_ipv4", resolve)

    svc = _direct_service("192.168.10.50", "home.lan", dev_mode=True)
    url = await svc.expose(ws_id="alice-myapp", node_ip="portal", host_port=41000)

    resolve.assert_not_awaited()
    assert url == "http://192.168.10.50:41000/?folder=/workspaces/alice-myapp"


@pytest.mark.asyncio
async def test_dev_mode_resolution_failure_falls_back_to_literal(monkeypatch) -> None:
    """Si la résolution échoue, on retombe sur le hostname littéral (best-effort)."""
    import portal.exposure as exposure_mod

    resolve = AsyncMock(side_effect=OSError("no address"))
    monkeypatch.setattr(exposure_mod, "resolve_ipv4", resolve)

    svc = _direct_service("portal", "home.lan", dev_mode=True)
    url = await svc.expose(ws_id="alice-myapp", node_ip="portal", host_port=41000)

    assert url == "http://portal:41000/?folder=/workspaces/alice-myapp"


@pytest.mark.asyncio
async def test_no_base_domain_resolves_hostname_workspace_host(monkeypatch) -> None:
    """Sans base_domain (fallback URL directe), workspace_host hostname est aussi résolu."""
    import portal.exposure as exposure_mod

    resolve = AsyncMock(return_value="192.168.10.42")
    monkeypatch.setattr(exposure_mod, "resolve_ipv4", resolve)

    svc = _direct_service("portal", "home.lan", dev_mode=False)
    url = await svc.expose(ws_id="alice-myapp", node_ip="portal", host_port=41000)

    resolve.assert_awaited_once_with("portal.home.lan")
    assert url == "http://192.168.10.42:41000/?folder=/workspaces/alice-myapp"
