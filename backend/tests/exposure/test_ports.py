from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_allocate_returns_port_in_range(db_engine) -> None:
    """allocate() retourne un port entre 40000 et 49999 quand la DB est vide."""
    from portal.exposure.ports import PortRegistry

    registry = PortRegistry()
    port = await registry.allocate("alice-myapp")
    assert 40000 <= port <= 49999


@pytest.mark.asyncio
async def test_allocate_respects_used_ports(db_engine) -> None:
    """allocate() ne retourne pas un port déjà enregistré en DB."""
    from portal.db.engine import _get_engine
    from portal.db.workspace_status import upsert_status_db
    from portal.exposure.ports import PortRegistry

    async with _get_engine().begin() as conn:
        await upsert_status_db("alice-other", "running", conn, login="alice", host_port=40000)

    registry = PortRegistry()
    port = await registry.allocate("alice-myapp")
    assert port == 40001


@pytest.mark.asyncio
async def test_allocate_no_collision_concurrent(db_engine) -> None:
    """Deux allocations concurrentes retournent des ports distincts."""
    from portal.exposure.ports import PortRegistry

    registry = PortRegistry()
    port1, port2 = await asyncio.gather(
        registry.allocate("alice-app1"),
        registry.allocate("alice-app2"),
    )
    assert port1 != port2
    assert 40000 <= port1 <= 49999
    assert 40000 <= port2 <= 49999


@pytest.mark.asyncio
async def test_reserved_pruned_after_db_confirmation(db_engine) -> None:
    """_reserved est purgé des ports confirmés en DB à chaque allocate()."""
    from portal.db.engine import _get_engine
    from portal.db.workspace_status import upsert_status_db
    from portal.exposure.ports import PortRegistry

    registry = PortRegistry()

    # Première allocation : port 40000 réservé en mémoire (DB vide)
    port1 = await registry.allocate("alice-app1")
    assert port1 == 40000

    # Simuler la persistance en DB (comme ExposureService le ferait)
    async with _get_engine().begin() as conn:
        await upsert_status_db("alice-app1", "running", conn, login="alice", host_port=40000)

    # Deuxième allocation : 40000 est maintenant en DB → _reserved épuré
    port2 = await registry.allocate("alice-app2")
    assert port2 == 40001
    assert 40000 not in registry._reserved
