"""Bug 015 — course sur l'allocation de ports compose (test Postgres réel).

Deux prepare_deployment concurrents sur le même nœud : sans le verrou advisory
et la réservation précoce, les deux lisent le même used_ports_on_node (aucun ne
voit l'allocation de l'autre, non persistée) et reçoivent le même port hôte.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from portal.compose.models import ComposeTemplate

pytestmark = pytest.mark.asyncio

_ALIAS_COMPOSE = (
    "services:\n"
    "  browser:\n"
    "    image: chromium:1.0.0\n"
    "    ports:\n"
    "      - chromium>3000:3000\n"
)


async def test_prepare_deployment_concurrent_disjoint_ports(
    db_engine_concurrent, monkeypatch
) -> None:
    from portal.compose import ports as ports_mod
    from portal.compose import service
    from portal.compose.db import create_template

    host = SimpleNamespace(name="n1", type="ssh", address="root@x", host_cert_slug="s")
    monkeypatch.setattr(service, "_host_for_node", lambda node_id: host)
    # Pas de nœud réel : seuls les ports persistés en DB comptent ici.
    monkeypatch.setattr(ports_mod, "_live_used_ports", AsyncMock(return_value=set()))

    tpl = ComposeTemplate(
        id="chromium", name="Chromium", version="1",
        compose_content=_ALIAS_COMPOSE, parameters=[], source="user",
    )
    async with db_engine_concurrent.connect() as c0:
        await create_template(c0, tpl)
        await c0.commit()

    ports_by_dep: dict[str, list[int]] = {}

    async def prepare_and_commit(conn, key: str) -> None:
        uid, _pm, host_ports, _cc = await service.prepare_deployment(
            conn,
            name=f"dep-{key}",
            template=tpl,
            node_id="n1",
            owner_login="alice",
            env_values={},
        )
        ports_by_dep[key] = host_ports
        await conn.commit()

    async with (
        db_engine_concurrent.connect() as c1,
        db_engine_concurrent.connect() as c2,
    ):
        await asyncio.gather(prepare_and_commit(c1, "a"), prepare_and_commit(c2, "b"))

    assert ports_by_dep["a"] != ports_by_dep["b"], (
        "deux déploiements concurrents sur le même nœud ont reçu le même port"
    )
    assert set(ports_by_dep["a"]).isdisjoint(ports_by_dep["b"])
