"""Primitives MCP de gestion des règles d'automates (scope admin).

`automation_rule_upsert` crée ou modifie une règle par son slug — même validation
que l'API admin (registre d'events fermé, arbre `RuleTree`, en-têtes value XOR
secret_ref). `automation_rule_get` / `automation_rule_list` lisent l'existant.
Création : curseur posé au sommet du journal (seuls les events À VENIR sont
exécutés ; le rattrapage des existants reste explicite via le backfill).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncConnection

from ...db import app_event as je
from ...db import automation as adb
from .errors import DevpodToolError


def _summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "slug": row["slug"],
        "label": row["label"],
        "active": row["active"],
        "event_types": row["event_types"],
        "position": row["position"],
        "stop_chain": row["stop_chain"],
        "delay_minutes": row["delay_minutes"],
    }


async def _by_slug(conn: AsyncConnection, slug: str) -> dict[str, Any] | None:
    for row in await adb.list_all(conn):
        if row["slug"] == slug:
            return row
    return None


async def _rule_list(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    return [_summary(r) for r in await adb.list_all(conn)]


async def _rule_get(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    slug = str(args.get("slug") or "").strip()
    if not slug:
        raise DevpodToolError("slug requis")
    row = await _by_slug(conn, slug)
    if row is None:
        raise DevpodToolError(f"règle introuvable : {slug!r}")
    return {**_summary(row), "tree": row["tree"]}


async def _rule_upsert(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    # Helpers de validation partagés avec l'API admin (source unique). L'arbre porte
    # ses en-têtes par appel/filtre — plus d'en-têtes au niveau règle.
    from ...routes.automations import _validate, _validated_tree

    slug = str(args.get("slug") or "").strip()
    if not slug:
        raise DevpodToolError("slug requis")

    try:
        fields: dict[str, Any] = {}
        for key in ("label", "active", "stop_chain", "delay_minutes"):
            if key in args and args[key] is not None:
                fields[key] = args[key]
        if args.get("event_types") is not None:
            _validate(list(args["event_types"]))
            fields["event_types"] = list(args["event_types"])
        if args.get("tree") is not None:
            if not isinstance(args["tree"], dict):
                raise DevpodToolError("tree doit être un objet JSON (arbre de règle)")
            fields["tree"] = _validated_tree(args["tree"])
    except HTTPException as exc:
        raise DevpodToolError(str(exc.detail)) from exc
    except (TypeError, ValueError) as exc:
        raise DevpodToolError(f"arguments invalides : {exc}") from exc

    existing = await _by_slug(conn, slug)
    if existing is None:
        if "label" not in fields or "event_types" not in fields:
            raise DevpodToolError(
                f"règle inconnue : {slug!r} — label et event_types requis pour la créer"
            )
        fields.setdefault("tree", _validated_tree({}))
        row = await adb.create(
            conn,
            slug=slug,
            position=await adb.max_position(conn) + 1,
            **fields,
        )
        await adb.set_cursor(conn, row["id"], await je.latest_seq(conn))
        created = True
        rule_id = row["id"]
    else:
        rule_id = existing["id"]
        if fields:
            await adb.update_fields(conn, rule_id, **fields)
        created = False
    fresh = await adb.get(conn, rule_id)
    assert fresh is not None
    return {"created": created, **_summary(fresh), "tree": fresh["tree"]}


AUTOMATION_IMPLS = {
    "automation_rule_list": _rule_list,
    "automation_rule_get": _rule_get,
    "automation_rule_upsert": _rule_upsert,
}
