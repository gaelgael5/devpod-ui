"""API admin du moteur d'automates : contrats OpenAPI, automates, runs, simulation.

Toutes les routes sont admin (`require_admin`). Montées sous `/admin/automations`.
Les routes littérales (`/contracts`, `/reorder`, `/inject-test-event`, `/backfill`)
sont déclarées AVANT `/{automation_id}` pour ne pas être capturées par le paramètre.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..automations import contracts as ct
from ..automations import simulate
from ..automations.runner import replay_run
from ..db import app_event as je
from ..db import automation as adb
from ..db import automation_run as ar
from ..db import openapi_contract as oc
from ..db.engine import get_conn
from ..events.models import EVENT_TYPES

router = APIRouter(tags=["automations"])

_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_Admin = Annotated[UserInfo, Depends(require_admin)]
_Conn = Annotated[AsyncConnection, Depends(get_conn)]


# ─── Modèles ──────────────────────────────────────────────────────────────────


class ContractCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    category: str = ""
    source_url: str | None = None
    raw_spec: dict[str, Any] | None = None


class ContractUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = None
    category: str | None = None
    # source_url : "" efface l'URL (import manuel figé) ; une URL non vide la met à jour.
    source_url: str | None = None
    # Re-fetch la spec depuis la nouvelle source_url après changement (défaut True).
    refresh: bool = True


class HeaderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    value: str | None = None
    secret_ref: str | None = None


class AutomationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    event_types: list[str]
    contract_ref: str
    operation_id: str
    url: str
    http_method: str
    body_template: str | None = None
    delay_minutes: int = 0
    stop_chain: bool = False
    headers: list[HeaderIn] = Field(default_factory=list)
    active: bool = False


class AutomationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = None
    event_types: list[str] | None = None
    contract_ref: str | None = None
    operation_id: str | None = None
    url: str | None = None
    http_method: str | None = None
    body_template: str | None = None
    delay_minutes: int | None = None
    stop_chain: bool | None = None
    headers: list[HeaderIn] | None = None
    active: bool | None = None


class ReorderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ordered_ids: list[str]


class InjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["user", "host", "workspace", "session"]
    workspace: str | None = None
    host_name: str | None = None
    session: str | None = None


def _validate(event_types: list[str], http_method: str) -> None:
    unknown = set(event_types) - EVENT_TYPES
    if unknown:
        raise HTTPException(status_code=422, detail=f"event_types inconnus : {sorted(unknown)}")
    if http_method.upper() not in _HTTP_METHODS:
        raise HTTPException(status_code=422, detail=f"http_method invalide : {http_method!r}")


def _headers_payload(headers: list[HeaderIn]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for h in headers:
        if (h.value is None) == (h.secret_ref is None):
            raise HTTPException(
                status_code=422,
                detail=f"en-tête {h.name!r} : value XOR secret_ref requis",
            )
        out.append({"name": h.name, "value": h.value, "secret_ref": h.secret_ref})
    return out


# ─── Contrats OpenAPI ─────────────────────────────────────────────────────────


@router.get("/contracts")
async def list_contracts(_: _Admin, conn: _Conn) -> list[dict[str, Any]]:
    return [
        {k: v for k, v in c.items() if k != "raw_spec"} for c in await oc.list_all(conn)
    ]


@router.post("/contracts", status_code=201)
async def create_contract(body: ContractCreate, _: _Admin, conn: _Conn) -> dict[str, Any]:
    if body.raw_spec is not None:
        spec = body.raw_spec
    elif body.source_url:
        spec = await ct.fetch_spec(body.source_url)
    else:
        raise HTTPException(status_code=422, detail="source_url ou raw_spec requis")
    row = await oc.create(
        conn,
        label=body.label,
        category=body.category,
        raw_spec=spec,
        version=ct.extract_version(spec),
        source_url=body.source_url,
    )
    return {k: v for k, v in row.items() if k != "raw_spec"}


@router.get("/contracts/{contract_id}")
async def get_contract(contract_id: str, _: _Admin, conn: _Conn) -> dict[str, Any]:
    row = await oc.get(conn, contract_id)
    if row is None:
        raise HTTPException(status_code=404, detail="contrat introuvable")
    row["operations"] = ct.list_operations(row["raw_spec"])
    row["servers"] = ct.servers(row["raw_spec"])
    return row


@router.patch("/contracts/{contract_id}")
async def update_contract(
    contract_id: str, body: ContractUpdate, _: _Admin, conn: _Conn
) -> dict[str, Any]:
    """Édite un contrat : renommer (label) et/ou changer sa source_url.

    Si la source_url change vers une URL non vide et `refresh` (défaut), la spec est
    re-téléchargée (anti-SSRF) et remplacée. source_url="" fige le contrat en import
    manuel (garde le raw_spec courant).
    """
    current = await oc.get(conn, contract_id)
    if current is None:
        raise HTTPException(status_code=404, detail="contrat introuvable")
    fields = body.model_dump(exclude_unset=True)
    new_url = fields.get("source_url")
    spec = None
    version = None
    if body.refresh and body.source_url:
        spec = await ct.fetch_spec(body.source_url)
        version = ct.extract_version(spec)
    updated = await oc.update_spec(
        conn,
        contract_id,
        label=fields.get("label"),
        category=fields.get("category"),
        source_url=new_url,
        raw_spec=spec,
        version=version,
    )
    assert updated is not None
    return {k: v for k, v in updated.items() if k != "raw_spec"}


@router.post("/contracts/{contract_id}/refresh")
async def refresh_contract(contract_id: str, _: _Admin, conn: _Conn) -> dict[str, Any]:
    row = await oc.get(conn, contract_id)
    if row is None:
        raise HTTPException(status_code=404, detail="contrat introuvable")
    if not row["source_url"]:
        raise HTTPException(status_code=422, detail="contrat sans source_url (import manuel)")
    spec = await ct.fetch_spec(row["source_url"])
    updated = await oc.update_spec(
        conn, contract_id, raw_spec=spec, version=ct.extract_version(spec)
    )
    assert updated is not None
    return {k: v for k, v in updated.items() if k != "raw_spec"}


@router.delete("/contracts/{contract_id}", status_code=204)
async def delete_contract(contract_id: str, _: _Admin, conn: _Conn) -> None:
    try:
        deleted = await oc.delete_contract(conn, contract_id)
    except Exception as exc:  # FK RESTRICT : contrat référencé par un automate
        raise HTTPException(status_code=409, detail="contrat référencé par un automate") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="contrat introuvable")


# ─── Simulation & rattrapage ──────────────────────────────────────────────────


@router.post("/inject-test-event")
async def inject_test_event(body: InjectIn, user: _Admin) -> dict[str, str]:
    return await simulate.inject_test_event(
        body.kind,
        actor=user.login,
        workspace=body.workspace,
        host_name=body.host_name,
        session=body.session,
    )


@router.post("/backfill")
async def backfill(user: _Admin) -> dict[str, int]:
    return await simulate.backfill(actor=user.login)


@router.post("/reorder")
async def reorder(body: ReorderIn, _: _Admin, conn: _Conn) -> dict[str, bool]:
    await adb.reorder(conn, body.ordered_ids)
    return {"reordered": True}


@router.get("/event-types")
async def list_event_types(_: _Admin) -> list[str]:
    """Types d'events déclencheurs disponibles (registre fermé) pour l'IHM."""
    return sorted(EVENT_TYPES)


# ─── Automates ────────────────────────────────────────────────────────────────


@router.get("")
async def list_automations(_: _Admin, conn: _Conn) -> list[dict[str, Any]]:
    autos = await adb.list_all(conn)
    for a in autos:
        a["pending"] = await je.count_after(
            conn, after_seq=a["last_seq"], event_types=a["event_types"]
        )
    return autos


@router.post("", status_code=201)
async def create_automation(body: AutomationCreate, _: _Admin, conn: _Conn) -> dict[str, Any]:
    _validate(body.event_types, body.http_method)
    if await oc.get(conn, body.contract_ref) is None:
        raise HTTPException(status_code=422, detail="contract_ref introuvable")
    position = await adb.max_position(conn) + 1
    row = await adb.create(
        conn,
        label=body.label,
        event_types=body.event_types,
        contract_ref=body.contract_ref,
        operation_id=body.operation_id,
        url=body.url,
        http_method=body.http_method.upper(),
        body_template=body.body_template,
        delay_minutes=body.delay_minutes,
        stop_chain=body.stop_chain,
        active=body.active,
        position=position,
    )
    await adb.set_headers(conn, row["id"], _headers_payload(body.headers))
    # Nouveau : curseur au sommet du journal — n'exécute que les events À VENIR
    # (le rattrapage des existants est explicite via /backfill).
    await adb.set_cursor(conn, row["id"], await je.latest_seq(conn))
    fresh = await adb.get(conn, row["id"])
    assert fresh is not None
    return await _detail(conn, fresh)


@router.get("/{automation_id}")
async def get_automation(automation_id: str, _: _Admin, conn: _Conn) -> dict[str, Any]:
    row = await adb.get(conn, automation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="automate introuvable")
    return await _detail(conn, row)


@router.patch("/{automation_id}")
async def update_automation(
    automation_id: str, body: AutomationUpdate, _: _Admin, conn: _Conn
) -> dict[str, Any]:
    current = await adb.get(conn, automation_id)
    if current is None:
        raise HTTPException(status_code=404, detail="automate introuvable")
    fields = body.model_dump(exclude_unset=True, exclude={"headers"})
    if "http_method" in fields and fields["http_method"] is not None:
        fields["http_method"] = fields["http_method"].upper()
    et = body.event_types if body.event_types is not None else current["event_types"]
    hm = fields.get("http_method") or current["http_method"]
    _validate(et, hm)
    if fields:
        await adb.update_fields(conn, automation_id, **fields)
    if body.headers is not None:
        await adb.set_headers(conn, automation_id, _headers_payload(body.headers))
    fresh = await adb.get(conn, automation_id)
    assert fresh is not None
    return await _detail(conn, fresh)


@router.delete("/{automation_id}", status_code=204)
async def delete_automation(automation_id: str, _: _Admin, conn: _Conn) -> None:
    if not await adb.delete_automation(conn, automation_id):
        raise HTTPException(status_code=404, detail="automate introuvable")


@router.get("/{automation_id}/runs")
async def list_runs(automation_id: str, _: _Admin, conn: _Conn) -> list[dict[str, Any]]:
    return await ar.list_for_automation(conn, automation_id, limit=20)


@router.delete("/{automation_id}/runs", status_code=204)
async def clear_runs(automation_id: str, _: _Admin, conn: _Conn) -> None:
    await ar.clear(conn, automation_id)


@router.post("/{automation_id}/runs/{run_id}/replay")
async def replay(automation_id: str, run_id: str, _: _Admin) -> dict[str, Any]:
    result = await replay_run(automation_id, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="automate, run ou event introuvable")
    return result


async def _detail(conn: AsyncConnection, row: dict[str, Any]) -> dict[str, Any]:
    row["headers"] = await adb.get_headers(conn, row["id"])
    row["last_seq"] = await adb.get_cursor(conn, row["id"])
    return row
