"""Rattachement d'un abonnement à ses machines, lu contre le vrai schéma.

Ce que ces tests protègent : le compte des places déjà promises. S'il est faux,
on vend une place qui n'existe pas, ou on ouvre une machine de plus pour rien.

Fixtures DB dans tests/conftest.py (postgres_url, db_engine, db_conn).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import insert

from portal.billing.allocation import Part
from portal.db.subscription_hosts import (
    detacher,
    machines_de,
    parts_de,
    places_promises,
    rattacher,
)
from portal.db.tables import hosts, offers, subscriptions, users


async def _seed_abonnement(conn, *, login: str = "alice", offre: str = "solo") -> str:
    await conn.execute(
        insert(users).values(
            login=login,
            version="1",
            secret_ns=str(uuid.uuid4()),
            default_ide="openvscode",
            default_idle_timeout="2h",
            harpocrate_api_key="",
        )
    )
    await conn.execute(insert(offers).values(slug=offre))
    sub_id = str(uuid.uuid4())
    await conn.execute(
        insert(subscriptions).values(
            id=sub_id,
            login=login,
            offer_slug=offre,
            country_code="FR",
            currency="EUR",
            amount_minor=1200,
        )
    )
    return sub_id


async def _seed_host(conn, nom: str) -> None:
    await conn.execute(insert(hosts).values(name=nom, type="docker-tls"))


@pytest.mark.asyncio
async def test_rattacher_puis_relire_la_part(db_conn):
    sub = await _seed_abonnement(db_conn)
    await _seed_host(db_conn, "vm1")

    await rattacher(sub, "vm1", 3, db_conn)

    assert await parts_de(sub, db_conn) == [Part(host_name="vm1", allocated_workspaces=3)]


@pytest.mark.asyncio
async def test_machine_dediee_sans_part(db_conn):
    """`None` = pas de plafond commercial : la capacité physique gouverne seule."""
    sub = await _seed_abonnement(db_conn)
    await _seed_host(db_conn, "vm1")

    await rattacher(sub, "vm1", None, db_conn)

    assert await parts_de(sub, db_conn) == []
    assert await machines_de(sub, db_conn) == ["vm1"]


@pytest.mark.asyncio
async def test_rejouer_le_rattachement_remplace_la_part(db_conn):
    """Un webhook rejoué est la norme : il ne doit pas cumuler deux lignes."""
    sub = await _seed_abonnement(db_conn)
    await _seed_host(db_conn, "vm1")

    await rattacher(sub, "vm1", 3, db_conn)
    await rattacher(sub, "vm1", 5, db_conn)

    assert await parts_de(sub, db_conn) == [Part(host_name="vm1", allocated_workspaces=5)]


@pytest.mark.asyncio
async def test_parts_sur_plusieurs_machines(db_conn):
    sub = await _seed_abonnement(db_conn)
    await _seed_host(db_conn, "vm1")
    await _seed_host(db_conn, "vm2")

    await rattacher(sub, "vm1", 3, db_conn)
    await rattacher(sub, "vm2", 2, db_conn)

    assert sorted(p.host_name for p in await parts_de(sub, db_conn)) == ["vm1", "vm2"]
    assert sum(p.allocated_workspaces for p in await parts_de(sub, db_conn)) == 5


@pytest.mark.asyncio
async def test_places_promises_somme_les_abonnements_de_la_machine(db_conn):
    """Le chiffre qui décide si la machine peut encore accueillir quelqu'un."""
    a = await _seed_abonnement(db_conn, login="alice", offre="solo")
    b = await _seed_abonnement(db_conn, login="bob", offre="duo")
    await _seed_host(db_conn, "vm1")

    await rattacher(a, "vm1", 3, db_conn)
    await rattacher(b, "vm1", 4, db_conn)

    assert await places_promises("vm1", db_conn) == 7


@pytest.mark.asyncio
async def test_places_promises_ignore_les_dediees(db_conn):
    """Une machine dédiée n'a pas de part : elle ne se compte pas en places."""
    sub = await _seed_abonnement(db_conn)
    await _seed_host(db_conn, "vm1")
    await rattacher(sub, "vm1", None, db_conn)

    assert await places_promises("vm1", db_conn) == 0


@pytest.mark.asyncio
async def test_machine_sans_rattachement_ne_promet_rien(db_conn):
    await _seed_host(db_conn, "libre")

    assert await places_promises("libre", db_conn) == 0


@pytest.mark.asyncio
async def test_detacher_libere_la_place(db_conn):
    sub = await _seed_abonnement(db_conn)
    await _seed_host(db_conn, "vm1")
    await rattacher(sub, "vm1", 3, db_conn)

    await detacher(sub, "vm1", db_conn)

    assert await parts_de(sub, db_conn) == []
    assert await places_promises("vm1", db_conn) == 0


@pytest.mark.asyncio
async def test_part_nulle_refusee_par_le_schema(db_conn):
    """Zéro place n'est pas un rattachement : la base doit le refuser aussi."""
    from sqlalchemy.exc import IntegrityError

    sub = await _seed_abonnement(db_conn)
    await _seed_host(db_conn, "vm1")

    with pytest.raises(IntegrityError):
        await rattacher(sub, "vm1", 0, db_conn)
