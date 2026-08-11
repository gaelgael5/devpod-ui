"""Repos du moteur d'automates : contrats, automation/scope/header/cursor, runs.

DB réelle (SAVEPOINT `db_conn`). Skippés en local faute de Docker ; tournent sur
un env avec Postgres (test1).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db import automation as a
from portal.db import automation_run as ar
from portal.db import openapi_contract as oc

_SPEC = {"openapi": "3.0.0", "info": {"version": "1.2.3"}, "paths": {}}


async def _contract(conn: AsyncConnection) -> str:
    row = await oc.create(conn, label="Termix", raw_spec=_SPEC, version="1.2.3")
    return row["id"]


_TREE = {
    "version": 1,
    "blocks": [
        {
            "label": "",
            "filter": None,
            "calls": [
                {
                    "name": "putHost",
                    "url": "https://termix.example.org/api/hosts",
                    "http_method": "PUT",
                    "body_template": None,
                    "contract_ref": None,
                    "operation_id": None,
                }
            ],
            "blocks": [],
        }
    ],
}


async def _automation(conn: AsyncConnection, **over: object) -> str:
    over.pop("contract_ref", None)  # compat appels existants (plus de FK contrat)
    fields = {
        "label": "sync-hosts",
        "slug": f"a-{uuid.uuid4().hex[:8]}",  # unique (contrainte uq_automation_slug)
        "event_types": ["test_server.updated"],
        "tree": _TREE,
        **over,
    }
    row = await a.create(conn, **fields)
    return row["id"]


# ─── Contrats ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_contract_crud(db_conn: AsyncConnection) -> None:
    cid = await _contract(db_conn)
    got = await oc.get(db_conn, cid)
    assert got is not None and got["version"] == "1.2.3"
    assert got["category"] == ""  # défaut
    updated = await oc.update_spec(db_conn, cid, label="Termix v2", version="2.0.0")
    assert updated is not None and updated["label"] == "Termix v2" and updated["version"] == "2.0.0"
    assert [c["id"] for c in await oc.list_all(db_conn)] == [cid]
    assert await oc.delete_contract(db_conn, cid) is True
    assert await oc.get(db_conn, cid) is None


@pytest.mark.asyncio
async def test_contract_category_create_update_and_sort(db_conn: AsyncConnection) -> None:
    a = await oc.create(db_conn, label="B-svc", raw_spec=_SPEC, category="zeta")
    b = await oc.create(db_conn, label="A-svc", raw_spec=_SPEC, category="alpha")
    c = await oc.create(db_conn, label="No-cat", raw_spec=_SPEC)  # category ""
    # list_all trié par (category, label) : "" en premier alphabétiquement côté SQL.
    order = [(x["category"], x["label"]) for x in await oc.list_all(db_conn)]
    assert order == [("", "No-cat"), ("alpha", "A-svc"), ("zeta", "B-svc")]
    upd = await oc.update_spec(db_conn, a["id"], category="alpha")
    assert upd is not None and upd["category"] == "alpha"
    assert b["id"] and c["id"]


# ─── Automates ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_automation_created_disabled(db_conn: AsyncConnection) -> None:
    aid = await _automation(db_conn)
    row = await a.get(db_conn, aid)
    assert row is not None
    assert row["active"] is False  # créé désactivé
    assert row["event_types"] == ["test_server.updated"]


@pytest.mark.asyncio
async def test_slug_exists_and_tree_persisted(db_conn: AsyncConnection) -> None:
    aid = await _automation(db_conn, slug="sync-hosts")
    assert await a.slug_exists(db_conn, "sync-hosts") is True
    assert await a.slug_exists(db_conn, "sync-hosts", exclude_id=aid) is False
    assert await a.slug_exists(db_conn, "autre") is False
    row = await a.get(db_conn, aid)
    assert row is not None
    assert row["tree"]["blocks"][0]["calls"][0]["name"] == "putHost"


@pytest.mark.asyncio
async def test_update_and_reorder(db_conn: AsyncConnection) -> None:
    a1 = await _automation(db_conn, label="a1", position=0)
    a2 = await _automation(db_conn, label="a2", position=1)
    assert await a.max_position(db_conn) == 1
    await a.update_fields(db_conn, a1, active=True, delay_minutes=5)
    row = await a.get(db_conn, a1)
    assert row is not None and row["active"] is True and row["delay_minutes"] == 5
    await a.reorder(db_conn, [a2, a1])
    listed = await a.list_all(db_conn)
    assert [r["id"] for r in listed] == [a2, a1]


@pytest.mark.asyncio
async def test_create_route_persists_tree(db_conn: AsyncConnection) -> None:
    # Régression : le handler de création doit persister l'arbre NORMALISÉ.
    from portal.routes.automations import AutomationCreate, create_automation

    body = AutomationCreate(
        label="sync-user",
        event_types=["test_server.updated"],
        tree={
            "blocks": [
                {
                    "filter": {
                        "url": "https://termix.example.org/users/list",
                        "jsonpath": '$.users[?(@.username=="{user.sub}")]',
                        "operator": "exists",
                    },
                    "calls": [
                        {
                            "name": "putHost",
                            "url": "https://termix.example.org/api/hosts",
                            "http_method": "POST",
                        }
                    ],
                }
            ]
        },
    )
    created = await create_automation(body, _=None, conn=db_conn)  # type: ignore[arg-type]
    row = await a.get(db_conn, created["id"])
    assert row is not None
    blk = row["tree"]["blocks"][0]
    assert blk["filter"]["operator"] == "exists"
    assert blk["calls"][0]["body_template"] is None  # défauts matérialisés


@pytest.mark.asyncio
async def test_headers_persisted_in_tree(db_conn: AsyncConnection) -> None:
    # Les en-têtes vivent dans l'arbre (par appel), plus dans une table dédiée.
    tree = {
        "version": 1,
        "blocks": [
            {
                "label": "",
                "filter": None,
                "calls": [
                    {
                        "name": "call1",
                        "url": "https://x/y",
                        "http_method": "POST",
                        "headers": [
                            {
                                "name": "Authorization",
                                "secret_ref": "${system://termix-token}",
                                "value_prefix": "Bearer ",
                                "enabled": False,
                            }
                        ],
                    }
                ],
                "blocks": [],
            }
        ],
    }
    aid = await _automation(db_conn, tree=tree)
    row = await a.get(db_conn, aid)
    assert row is not None
    hdr = row["tree"]["blocks"][0]["calls"][0]["headers"][0]
    assert hdr["secret_ref"] == "${system://termix-token}"
    assert hdr["value_prefix"] == "Bearer " and hdr["enabled"] is False


@pytest.mark.asyncio
async def test_cursor_upsert(db_conn: AsyncConnection) -> None:
    aid = await _automation(db_conn)
    assert await a.get_cursor(db_conn, aid) == 0
    await a.set_cursor(db_conn, aid, 42)
    await a.set_cursor(db_conn, aid, 99)
    assert await a.get_cursor(db_conn, aid) == 99


@pytest.mark.asyncio
async def test_list_active_attaches_details(db_conn: AsyncConnection) -> None:
    aid = await _automation(db_conn, active=True)
    await a.set_cursor(db_conn, aid, 7)
    active = await a.list_active(db_conn)
    assert len(active) == 1
    assert active[0]["tree"]["blocks"][0]["calls"][0]["name"] == "putHost"
    assert active[0]["last_seq"] == 7


# ─── Runs (anti-rejeu) ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_claim_dedups_automatic_runs(db_conn: AsyncConnection) -> None:
    aid = await _automation(db_conn)
    first = await ar.claim(db_conn, automation_id=aid, event_seq=10, dedup_key="host:h1")
    assert first is not None
    second = await ar.claim(db_conn, automation_id=aid, event_seq=11, dedup_key="host:h1")
    assert second is None  # même version → pas de re-run automatique


@pytest.mark.asyncio
async def test_manual_run_escapes_dedup(db_conn: AsyncConnection) -> None:
    aid = await _automation(db_conn)
    await ar.claim(db_conn, automation_id=aid, event_seq=10, dedup_key="host:h1")
    m1 = await ar.record_manual(
        db_conn, automation_id=aid, event_seq=10, dedup_key="host:h1", status="ok"
    )
    m2 = await ar.record_manual(
        db_conn, automation_id=aid, event_seq=10, dedup_key="host:h1", status="ok"
    )
    assert m1 != m2  # rejeus manuels toujours autorisés


@pytest.mark.asyncio
async def test_finish_and_history_and_prune(db_conn: AsyncConnection) -> None:
    aid = await _automation(db_conn)
    for i in range(5):
        rid = await ar.claim(db_conn, automation_id=aid, event_seq=i, dedup_key=f"k{i}")
        assert rid is not None
        await ar.finish(db_conn, rid, status="ok", http_status=200, response_preview="OK")
    assert await ar.count(db_conn, aid) == 5
    purged = await ar.prune(db_conn, aid, keep=2)
    assert purged == 3
    assert await ar.count(db_conn, aid) == 2


@pytest.mark.asyncio
async def test_reset_stale_running_allows_rerun(db_conn: AsyncConnection) -> None:
    aid = await _automation(db_conn)
    await ar.claim(db_conn, automation_id=aid, event_seq=1, dedup_key="k")
    # Sans finish : la trace reste « running ». reset la supprime → re-claim possible.
    assert await ar.reset_stale_running(db_conn) == 1
    again = await ar.claim(db_conn, automation_id=aid, event_seq=1, dedup_key="k")
    assert again is not None


@pytest.mark.asyncio
async def test_clear_history(db_conn: AsyncConnection) -> None:
    aid = await _automation(db_conn)
    rid = await ar.claim(db_conn, automation_id=aid, event_seq=1, dedup_key="k")
    assert rid is not None
    await ar.finish(db_conn, rid, status="ok")
    assert await ar.clear(db_conn, aid) == 1
    assert await ar.count(db_conn, aid) == 0


@pytest.mark.asyncio
async def test_clear_after_seq_purges_replay_range(db_conn: AsyncConnection) -> None:
    aid = await _automation(db_conn)
    for i in (1, 2, 3):
        rid = await ar.claim(db_conn, automation_id=aid, event_seq=i, dedup_key=f"k{i}")
        assert rid is not None
        await ar.finish(db_conn, rid, status="ok")
    # Repositionne à seq=1 → purge des runs des events 2 et 3.
    assert await ar.clear_after_seq(db_conn, 1) == 2
    assert await ar.count(db_conn, aid) == 1


@pytest.mark.asyncio
async def test_set_all_cursors(db_conn: AsyncConnection) -> None:
    cid = await _contract(db_conn)
    a1 = await _automation(db_conn, contract_ref=cid)
    a2 = await _automation(db_conn, contract_ref=cid)
    assert await a.set_all_cursors(db_conn, 42) == 2
    assert await a.get_cursor(db_conn, a1) == 42
    assert await a.get_cursor(db_conn, a2) == 42


@pytest.mark.asyncio
async def test_purge_older_than(db_conn: AsyncConnection) -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from portal.db.tables import automation_run as _r

    aid = await _automation(db_conn)
    rid = await ar.claim(db_conn, automation_id=aid, event_seq=1, dedup_key="k")
    assert rid is not None
    await ar.finish(db_conn, rid, status="ok")
    # Vieillit artificiellement le run à 8 jours.
    await db_conn.execute(
        update(_r).where(_r.c.id == rid).values(created_at=datetime.now(UTC) - timedelta(days=8))
    )
    assert await ar.purge_older_than(db_conn, datetime.now(UTC) - timedelta(days=7)) == 1
    assert await ar.count(db_conn, aid) == 0
