"""API admin du moteur d'automates : contrats OpenAPI, automates, runs, simulation.

Toutes les routes sont admin (`require_admin`). Montées sous `/admin/automations`.
Les routes littérales (`/contracts`, `/reorder`, `/inject-test-event`, `/backfill`)
sont déclarées AVANT `/{automation_id}` pour ne pas être capturées par le paramètre.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..automations import contracts as ct
from ..automations import simulate
from ..automations.filter_eval import OPERATORS as _FILTER_OPS
from ..automations.runner import replay_run
from ..db import app_event as je
from ..db import automation as adb
from ..db import automation_run as ar
from ..db import openapi_contract as oc
from ..db.engine import get_conn
from ..events.models import EVENT_TYPES
from ..secrets import system as sysec

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
    # Préfixe concaténé devant la valeur/secret résolu (ex. « Bearer »).
    value_prefix: str = ""
    # required : en-tête d'auth du contrat ; enabled : ligne active à l'appel.
    required: bool = False
    enabled: bool = True


class AutomationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    # slug vide → dérivé du label (normalisé). Unique.
    slug: str = ""
    event_types: list[str]
    contract_ref: str
    operation_id: str
    url: str
    http_method: str
    body_template: str | None = None
    delay_minutes: int = 0
    stop_chain: bool = False
    # Priorité d'exécution (position). None → ajouté en fin de liste.
    position: int | None = None
    headers: list[HeaderIn] = Field(default_factory=list)
    active: bool = False
    # Onglet Filtre : appel d'API préliminaire + règle d'évaluation.
    filter_contract_ref: str | None = None
    filter_operation_id: str | None = None
    filter_url: str | None = None
    filter_method: str | None = None
    filter_body: str | None = None
    filter_jsonpath: str | None = None
    filter_operator: str | None = None
    filter_expected: str | None = None


class AutomationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = None
    slug: str | None = None
    event_types: list[str] | None = None
    contract_ref: str | None = None
    operation_id: str | None = None
    url: str | None = None
    http_method: str | None = None
    body_template: str | None = None
    delay_minutes: int | None = None
    stop_chain: bool | None = None
    position: int | None = None
    headers: list[HeaderIn] | None = None
    active: bool | None = None
    filter_contract_ref: str | None = None
    filter_operation_id: str | None = None
    filter_url: str | None = None
    filter_method: str | None = None
    filter_body: str | None = None
    filter_jsonpath: str | None = None
    filter_operator: str | None = None
    filter_expected: str | None = None


class FilterCallIn(BaseModel):
    """Appel d'API ad hoc pour l'onglet Filtre : exécuté tel quel, payload + éval renvoyés.

    Si jsonpath+operator sont fournis, la règle est évaluée sur la réponse ;
    `variables` (nom→valeur d'exemple) rend les `{var}` de url/body/jsonpath/expected.
    """

    model_config = ConfigDict(extra="forbid")
    url: str
    http_method: str
    headers: list[HeaderIn] = Field(default_factory=list)
    body: str | None = None
    jsonpath: str | None = None
    operator: str | None = None
    expected: str | None = None
    variables: dict[str, str] = Field(default_factory=dict)


class ReorderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ordered_ids: list[str]


# Slug d'un secret système (réf `${system://<slug>}`) : minuscules, chiffres, - et _.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class SystemSecretIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    label: str
    value: str


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


def _validate_filter_operator(operator: str | None) -> None:
    if operator and operator not in _FILTER_OPS:
        raise HTTPException(status_code=422, detail=f"opérateur de filtre invalide : {operator!r}")


def _normalize_slug(raw: str) -> str:
    """Normalise en slug : minuscules, [a-z0-9] conservés, autres → '-', borné à 64."""
    s = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
    return s[:64]


def _resolve_slug(slug: str, label: str) -> str:
    """Slug explicite (normalisé) ou dérivé du label. Lève 422 si vide/invalide."""
    candidate = _normalize_slug(slug) if slug else _normalize_slug(label)
    if not _SLUG_RE.match(candidate):
        raise HTTPException(status_code=422, detail=f"slug invalide : {slug or label!r}")
    return candidate


def _headers_payload(headers: list[HeaderIn]) -> list[dict[str, Any]]:
    """Normalise les en-têtes. value et secret_ref sont exclusifs ; les deux vides =
    stub d'auth non encore configuré (autorisé, ignoré à l'appel)."""
    out: list[dict[str, Any]] = []
    for h in headers:
        if h.value is not None and h.secret_ref is not None:
            raise HTTPException(
                status_code=422,
                detail=f"en-tête {h.name!r} : value et secret_ref exclusifs",
            )
        out.append(
            {
                "name": h.name,
                "value": h.value,
                "secret_ref": h.secret_ref,
                "value_prefix": h.value_prefix,
                "required": h.required,
                "enabled": h.enabled,
            }
        )
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


class CursorResetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Nouveau curseur (dernier seq considéré traité). Les events > seq seront réévalués.
    seq: int


@router.post("/reset-cursor")
async def reset_cursor(body: CursorResetIn, _: _Admin, conn: _Conn) -> dict[str, int]:
    """Repositionne le curseur global : tous les automates repartent à `seq`.

    Purge aussi l'anti-rejeu des events > seq (runs supprimés) pour qu'ils soient
    réellement ré-évalués « comme si le curseur avançait normalement ».
    """
    n = await adb.set_all_cursors(conn, body.seq)
    cleared = await ar.clear_after_seq(conn, body.seq)
    return {"automations": n, "runs_cleared": cleared}


@router.post("/test-call")
async def test_call(body: FilterCallIn, _: _Admin) -> dict[str, Any]:
    """Exécute l'appel de filtre (SSRF-pinné), renvoie le payload et, si une règle
    (jsonpath+operator) est fournie, son évaluation.

    Les `{var}` de url/body/jsonpath/expected sont rendus avec `variables` (valeurs
    d'exemple fournies par l'IHM ; à l'exécution ce sont celles de l'event).
    """
    import httpx

    from ..automations import filter_eval as feval
    from ..automations.runner import _resolve_headers, render_template
    from ..routes._ssrf import pinned_request

    if body.http_method.upper() not in _HTTP_METHODS:
        raise HTTPException(status_code=422, detail=f"http_method invalide : {body.http_method!r}")
    if body.operator is not None and body.operator not in feval.OPERATORS:
        raise HTTPException(status_code=422, detail=f"opérateur invalide : {body.operator!r}")
    ctx = body.variables
    url = render_template(body.url, ctx)
    raw_body = render_template(body.body, ctx) if body.body else None
    headers = await _resolve_headers(_headers_payload(body.headers))
    content = raw_body.encode() if raw_body else None
    if content is not None:
        headers.setdefault("content-type", "application/json")
    try:
        async with httpx.AsyncClient() as client:
            resp = await pinned_request(
                client,
                body.http_method,
                url,
                headers=headers,
                content=content,
                timeout=10.0,
                max_bytes=64 * 1024,
            )
    except Exception as exc:  # DNS/SSRF/timeout/connexion
        return {"ok": False, "error": str(exc)}
    result: dict[str, Any] = {
        "ok": True,
        "status_code": resp.status_code,
        "body": resp.text[:64_000],
    }
    if body.jsonpath and body.operator:
        expected = render_template(body.expected, ctx) if body.expected else None
        try:
            passed, matches = feval.evaluate(
                resp.json(), render_template(body.jsonpath, ctx), body.operator, expected
            )
            result["evaluation"] = {"passed": passed, "matches": matches}
        except Exception as exc:  # JSON non parsable / JSONPath invalide
            result["evaluation"] = {"error": str(exc)}
    return result


@router.get("/event-types")
async def list_event_types(_: _Admin) -> list[str]:
    """Types d'events déclencheurs disponibles (registre fermé) pour l'IHM."""
    return sorted(EVENT_TYPES)


@router.get("/event-variables")
async def list_event_variables(_: _Admin) -> dict[str, list[str]]:
    """Variables de template par type d'event (`event.*`) — palette contextuelle IHM."""
    from ..events.schemas import variables_by_type

    return variables_by_type()


@router.get("/events")
async def list_journal_events(
    _: _Admin,
    conn: _Conn,
    limit: int = 50,
    before_seq: int | None = None,
    event_type: str | None = None,
) -> list[dict[str, Any]]:
    """Journal `app_event` (récent d'abord) : seq (= id de curseur), event_id, type, subject…

    Paginé par `before_seq` (seq < before_seq). `event_type` filtre optionnel.
    """
    return await je.list_recent(
        conn,
        limit=max(1, min(limit, 200)),
        before_seq=before_seq,
        event_type=event_type or None,
    )


# ─── Secrets système (résolvables en tâche de fond) ───────────────────────────
#
# Les en-têtes d'automate résolus par le runner (KEK, sans PIN utilisateur)
# référencent ces secrets via `${system://<slug>}`. La valeur n'est jamais relue.


@router.get("/secrets")
async def list_system_secrets(_: _Admin, conn: _Conn) -> list[dict[str, str]]:
    return await sysec.list_system_secrets(conn)


@router.post("/secrets", status_code=201)
async def create_system_secret(body: SystemSecretIn, _: _Admin, conn: _Conn) -> dict[str, str]:
    if not _SLUG_RE.match(body.slug):
        raise HTTPException(status_code=422, detail=f"slug invalide : {body.slug!r}")
    await sysec.ensure_system_user(conn)
    await sysec.store_system_secret(
        slug=body.slug,
        label=body.label,
        value=body.value,
        storage_type="local",
        vault_identifier="",
        conn=conn,
    )
    return {"slug": body.slug, "ref": f"${{system://{body.slug}}}"}


@router.delete("/secrets/{slug}", status_code=204)
async def delete_system_secret(slug: str, _: _Admin, conn: _Conn) -> None:
    await sysec.delete_system_secret(slug, conn)


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
    _validate_filter_operator(body.filter_operator)
    if await oc.get(conn, body.contract_ref) is None:
        raise HTTPException(status_code=422, detail="contract_ref introuvable")
    slug = _resolve_slug(body.slug, body.label)
    if await adb.slug_exists(conn, slug):
        raise HTTPException(status_code=409, detail=f"slug déjà utilisé : {slug!r}")
    position = body.position if body.position is not None else await adb.max_position(conn) + 1
    row = await adb.create(
        conn,
        label=body.label,
        slug=slug,
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
        filter_contract_ref=body.filter_contract_ref,
        filter_operation_id=body.filter_operation_id,
        filter_url=body.filter_url,
        filter_method=body.filter_method,
        filter_body=body.filter_body,
        filter_jsonpath=body.filter_jsonpath,
        filter_operator=body.filter_operator,
        filter_expected=body.filter_expected,
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
    if fields.get("slug"):
        slug = _resolve_slug(fields["slug"], current["label"])
        if await adb.slug_exists(conn, slug, exclude_id=automation_id):
            raise HTTPException(status_code=409, detail=f"slug déjà utilisé : {slug!r}")
        fields["slug"] = slug
    et = body.event_types if body.event_types is not None else current["event_types"]
    hm = fields.get("http_method") or current["http_method"]
    _validate(et, hm)
    _validate_filter_operator(body.filter_operator)
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
