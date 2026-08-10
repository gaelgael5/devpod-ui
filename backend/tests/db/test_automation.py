"""Repos du moteur d'automates : contrats, automation/scope/header/cursor, runs.

DB réelle (SAVEPOINT `db_conn`). Skippés en local faute de Docker ; tournent sur
un env avec Postgres (test1).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db import automation as a
from portal.db import automation_run as ar
from portal.db import openapi_contract as oc

_SPEC = {"openapi": "3.0.0", "info": {"version": "1.2.3"}, "paths": {}}


async def _contract(conn: AsyncConnection) -> str:
    row = await oc.create(conn, label="Termix", raw_spec=_SPEC, version="1.2.3")
    return row["id"]


async def _automation(conn: AsyncConnection, **over: object) -> str:
    cid = over.pop("contract_ref", None) or await _contract(conn)
    fields = {
        "label": "sync-hosts",
        "event_types": ["test_server.updated"],
        "contract_ref": cid,
        "operation_id": "putHost",
        "url": "https://termix.example.org/api/hosts",
        "http_method": "PUT",
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
async def test_scopes_dedup_and_replace(db_conn: AsyncConnection) -> None:
    aid = await _automation(db_conn)
    await a.set_scopes(db_conn, aid, ["proj", "proj", "*"])
    assert await a.get_scopes(db_conn, aid) == ["*", "proj"]
    await a.set_scopes(db_conn, aid, ["other"])
    assert await a.get_scopes(db_conn, aid) == ["other"]


@pytest.mark.asyncio
async def test_headers_value_and_secret(db_conn: AsyncConnection) -> None:
    aid = await _automation(db_conn)
    await a.set_headers(
        db_conn,
        aid,
        [
            {"name": "X-Env", "value": "prod"},
            {"name": "Authorization", "secret_ref": "${vault://termix-token}"},
        ],
    )
    hdrs = await a.get_headers(db_conn, aid)
    by_name = {h["name"]: h for h in hdrs}
    assert by_name["X-Env"]["value"] == "prod" and by_name["X-Env"]["secret_ref"] is None
    assert by_name["Authorization"]["secret_ref"] == "${vault://termix-token}"


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
    await a.set_scopes(db_conn, aid, ["*"])
    await a.set_headers(db_conn, aid, [{"name": "X", "value": "y"}])
    await a.set_cursor(db_conn, aid, 7)
    active = await a.list_active(db_conn)
    assert len(active) == 1
    assert active[0]["scopes"] == ["*"]
    assert active[0]["headers"][0]["name"] == "X"
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
