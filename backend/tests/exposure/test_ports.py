from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    (tmp_path / "routes").mkdir(parents=True)
    return tmp_path


@pytest.mark.asyncio
async def test_allocate_returns_port_in_range(data_root: Path) -> None:
    """allocate() retourne un port entre 40000 et 49999."""
    from portal.exposure.ports import PortRegistry

    registry = PortRegistry(data_root)
    port = await registry.allocate("alice-myapp")
    assert 40000 <= port <= 49999


@pytest.mark.asyncio
async def test_allocate_respects_used_ports(data_root: Path) -> None:
    """allocate() ne retourne pas un port déjà dans routes/*.json."""
    from portal.exposure.ports import PortRegistry

    # Pré-remplir le port 40000 dans un fichier de route
    (data_root / "routes" / "alice-other.json").write_text(
        json.dumps({"ws_id": "alice-other", "host_port": 40000}),
        encoding="utf-8",
    )

    registry = PortRegistry(data_root)
    port = await registry.allocate("alice-myapp")
    assert port == 40001


@pytest.mark.asyncio
async def test_allocate_no_collision_concurrent(data_root: Path) -> None:
    """Deux allocations concurrentes retournent des ports distincts."""
    from portal.exposure.ports import PortRegistry

    registry = PortRegistry(data_root)
    port1, port2 = await asyncio.gather(
        registry.allocate("alice-app1"),
        registry.allocate("alice-app2"),
    )
    assert port1 != port2
    assert 40000 <= port1 <= 49999
    assert 40000 <= port2 <= 49999


@pytest.mark.asyncio
async def test_allocate_ignores_corrupt_json(data_root: Path) -> None:
    """allocate() ignore les fichiers JSON corrompus sans lever d'exception."""
    from portal.exposure.ports import PortRegistry

    (data_root / "routes" / "corrupt.json").write_text("NOT JSON", encoding="utf-8")
    registry = PortRegistry(data_root)
    port = await registry.allocate("alice-myapp")
    assert 40000 <= port <= 49999


@pytest.mark.asyncio
async def test_allocate_ignores_non_int_host_port(data_root: Path) -> None:
    """allocate() ignore les host_port non entiers."""
    from portal.exposure.ports import PortRegistry

    (data_root / "routes" / "bad-port.json").write_text(
        json.dumps({"ws_id": "bad-port", "host_port": "not-a-number"}),
        encoding="utf-8",
    )
    registry = PortRegistry(data_root)
    port = await registry.allocate("alice-myapp")
    assert port == 40000  # port 40000 toujours libre


@pytest.mark.asyncio
async def test_reserved_pruned_after_disk_confirmation(data_root: Path) -> None:
    """_reserved est purgé des ports confirmés sur disque à chaque allocate()."""
    from portal.exposure.ports import PortRegistry

    registry = PortRegistry(data_root)
    # Première allocation : port 40000 réservé en mémoire (disk vide)
    port1 = await registry.allocate("alice-app1")
    assert port1 == 40000
    # Simuler la persistance sur disque (comme ExposureService le ferait)
    (data_root / "routes" / "alice-app1.json").write_text(
        json.dumps({"ws_id": "alice-app1", "host_port": 40000}),
        encoding="utf-8",
    )
    # Deuxième allocation : 40000 est maintenant sur disque
    # _reserved doit être purgé → 40000 est retiré de _reserved
    # L'état final : disk_ports={40000}, _reserved vide avant prune → used={40000}
    port2 = await registry.allocate("alice-app2")
    assert port2 == 40001
    # Vérifier que _reserved ne contient plus 40000 (il est sur disque)
    assert 40000 not in registry._reserved
