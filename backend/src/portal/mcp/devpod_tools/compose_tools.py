"""Implémentations MCP internes pour la galerie docker-compose.

Outils publiés :
  read  : compose_template_list, compose_template_get,
          compose_service_list, compose_service_logs, compose_service_status
  admin : compose_template_create, compose_template_update
  exec  : compose_service_start, compose_service_stop,
          compose_service_restart, compose_service_down
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from ...compose import db as cdb
from ...compose import service as csvc
from ...compose.models import ComposeParam, ComposeTemplate, validate_slug
from ...compose.ports import PortConflict
from ...compose.service import ComposeServiceError
from ...compose.validation import TemplateValidationError, validate_template
from ...config.store import load_user
from .errors import DevpodToolError


def _require_str(args: dict[str, Any], key: str) -> str:
    val = args.get(key)
    if not isinstance(val, str) or not val.strip():
        raise DevpodToolError(f"paramètre requis manquant ou vide: {key!r}")
    return val.strip()


def _opt_str(args: dict[str, Any], key: str, default: str = "") -> str:
    val = args.get(key, default)
    return str(val) if val is not None else default


def _opt_list(args: dict[str, Any], key: str) -> list[Any]:
    val = args.get(key, [])
    return list(val) if isinstance(val, list) else []


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

async def _compose_template_list(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    tag = args.get("tag")
    templates = await cdb.list_templates(conn, tag=str(tag) if tag else None)
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "tags": t.tags,
            "version": t.version,
            "source": t.source,
            "parameters": len(t.parameters),
        }
        for t in templates
    ]


async def _compose_template_get(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    tpl_id = _require_str(args, "template_id")
    tpl = await cdb.get_template(conn, tpl_id)
    if tpl is None:
        raise DevpodToolError(f"template inconnu: {tpl_id}")
    return tpl.model_dump(mode="json")


async def _compose_template_create(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    tpl_id = _require_str(args, "id")
    name = _require_str(args, "name")
    compose_content = _require_str(args, "compose_content")
    version = _opt_str(args, "version", "1")
    description = _opt_str(args, "description")
    tags = _opt_list(args, "tags")

    raw_params = _opt_list(args, "parameters")
    try:
        parameters = [ComposeParam.model_validate(p) for p in raw_params]
    except Exception as exc:
        raise DevpodToolError(f"paramètres invalides: {exc}") from exc

    try:
        validate_slug(tpl_id)
    except ValueError as exc:
        raise DevpodToolError(str(exc)) from exc

    if await cdb.get_template(conn, tpl_id) is not None:
        raise DevpodToolError(f"template {tpl_id!r} existe déjà")

    try:
        warnings = validate_template(compose_content, parameters)
    except TemplateValidationError as exc:
        raise DevpodToolError(str(exc)) from exc

    tpl = ComposeTemplate(
        id=tpl_id,
        name=name,
        description=description,
        tags=[str(t) for t in tags],
        version=version,
        compose_content=compose_content,
        parameters=parameters,
        source="user",
    )
    await cdb.create_template(conn, tpl)
    return {"id": tpl_id, "created": True, "warnings": warnings}


async def _compose_template_update(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    tpl_id = _require_str(args, "id")
    existing = await cdb.get_template(conn, tpl_id)
    if existing is None:
        raise DevpodToolError(f"template inconnu: {tpl_id}")

    compose_content = _require_str(args, "compose_content")
    name = _opt_str(args, "name", existing.name)
    version = _opt_str(args, "version", existing.version)
    description = _opt_str(args, "description", existing.description)
    tags_raw = args.get("tags")
    tags = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else existing.tags

    raw_params = args.get("parameters")
    if raw_params is None:
        parameters = existing.parameters
    else:
        try:
            parameters = [ComposeParam.model_validate(p) for p in raw_params]
        except Exception as exc:
            raise DevpodToolError(f"paramètres invalides: {exc}") from exc

    try:
        warnings = validate_template(compose_content, parameters)
    except TemplateValidationError as exc:
        raise DevpodToolError(str(exc)) from exc

    updated = existing.model_copy(
        update={
            "name": name,
            "description": description,
            "tags": tags,
            "version": version,
            "compose_content": compose_content,
            "parameters": parameters,
        }
    )
    await cdb.update_template(conn, updated)
    return {"id": tpl_id, "updated": True, "warnings": warnings}


# ---------------------------------------------------------------------------
# Services (déploiements)
# ---------------------------------------------------------------------------

async def _compose_service_list(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    node_id = args.get("node_id")
    deps = await cdb.list_deployments(conn, owner_login=owner_login)
    if node_id and isinstance(node_id, str):
        deps = [d for d in deps if d.node_id == node_id]
    return [
        {
            "id": d.id,
            "template_id": d.template_id,
            "node_id": d.node_id,
            "status": d.status,
            "host_ports": d.host_ports,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in deps
    ]


async def _compose_service_start(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    template_id = _require_str(args, "template_id")
    node_id = _require_str(args, "node_id")
    name = _require_str(args, "name")
    env_values: dict[str, str] = {
        k: str(v) for k, v in (args.get("env_values") or {}).items()
    }

    try:
        validate_slug(name)
    except ValueError as exc:
        raise DevpodToolError(str(exc)) from exc

    tpl = await cdb.get_template(conn, template_id)
    if tpl is None:
        raise DevpodToolError(f"template inconnu: {template_id}")

    missing = [p.key for p in tpl.parameters if p.required and p.key not in env_values]
    if missing:
        raise DevpodToolError(f"paramètres requis manquants: {missing}")

    if await cdb.get_deployment_by_slug(conn, name) is not None:
        raise DevpodToolError(f"déploiement {name!r} existe déjà")

    user_cfg = await load_user(owner_login)
    try:
        dep = await csvc.deploy(
            conn,
            name=name,
            template=tpl,
            node_id=node_id,
            owner_login=owner_login,
            secret_ns=user_cfg.secret_ns,
            env_values=env_values,
        )
    except PortConflict as exc:
        raise DevpodToolError(
            f"conflit de port: {sorted(exc.conflicts)} "
            f"(port libre suggéré: {exc.suggestion})"
        ) from exc
    except ComposeServiceError as exc:
        raise DevpodToolError(str(exc)) from exc

    return {
        "id": dep.id,
        "node_id": dep.node_id,
        "status": dep.status,
        "host_ports": dep.host_ports,
    }


async def _compose_service_stop(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    dep_id = _require_str(args, "deployment_id")
    dep = await cdb.get_deployment_by_slug(conn, dep_id)
    if dep is None or dep.owner_login != owner_login:
        raise DevpodToolError(f"déploiement inconnu: {dep_id}")
    try:
        await csvc.lifecycle(conn, dep.uid, "stop")
    except ComposeServiceError as exc:
        raise DevpodToolError(str(exc)) from exc
    return {"deployment_id": dep_id, "action": "stop"}


async def _compose_service_restart(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    dep_id = _require_str(args, "deployment_id")
    dep = await cdb.get_deployment_by_slug(conn, dep_id)
    if dep is None or dep.owner_login != owner_login:
        raise DevpodToolError(f"déploiement inconnu: {dep_id}")
    try:
        await csvc.lifecycle(conn, dep.uid, "restart")
    except ComposeServiceError as exc:
        raise DevpodToolError(str(exc)) from exc
    return {"deployment_id": dep_id, "action": "restart"}


async def _compose_service_logs(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    dep_id = _require_str(args, "deployment_id")
    dep = await cdb.get_deployment_by_slug(conn, dep_id)
    if dep is None or dep.owner_login != owner_login:
        raise DevpodToolError(f"déploiement inconnu: {dep_id}")
    service = args.get("service")
    tail = int(args.get("tail", 200))
    try:
        output = await csvc.fetch_logs(
            conn, dep.uid,
            service=str(service) if service else None,
            tail=min(max(tail, 1), 5000),
        )
    except ComposeServiceError as exc:
        raise DevpodToolError(str(exc)) from exc
    return {"deployment_id": dep_id, "output": output}


async def _compose_service_down(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    dep_id = _require_str(args, "deployment_id")
    confirm = args.get("confirm", False)
    if not confirm:
        raise DevpodToolError("confirm doit valoir true pour détruire un déploiement")
    dep = await cdb.get_deployment_by_slug(conn, dep_id)
    if dep is None or dep.owner_login != owner_login:
        raise DevpodToolError(f"déploiement inconnu: {dep_id}")
    try:
        await csvc.teardown(conn, dep.uid)
    except ComposeServiceError as exc:
        raise DevpodToolError(str(exc)) from exc
    return {"deployment_id": dep_id, "torn_down": True}


async def _compose_service_status(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    dep_id = _require_str(args, "deployment_id")
    dep = await cdb.get_deployment_by_slug(conn, dep_id)
    if dep is None or dep.owner_login != owner_login:
        raise DevpodToolError(f"déploiement inconnu: {dep_id}")
    try:
        status = await csvc.refresh_status(conn, dep.uid)
    except ComposeServiceError as exc:
        raise DevpodToolError(str(exc)) from exc
    return {"deployment_id": dep_id, "status": status, "host_ports": dep.host_ports}


COMPOSE_IMPLS = {
    "compose_template_list": _compose_template_list,
    "compose_template_get": _compose_template_get,
    "compose_template_create": _compose_template_create,
    "compose_template_update": _compose_template_update,
    "compose_service_list": _compose_service_list,
    "compose_service_start": _compose_service_start,
    "compose_service_stop": _compose_service_stop,
    "compose_service_restart": _compose_service_restart,
    "compose_service_logs": _compose_service_logs,
    "compose_service_down": _compose_service_down,
    "compose_service_status": _compose_service_status,
}
