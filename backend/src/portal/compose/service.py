"""Orchestration du cycle de vie d'un déploiement compose (spec 26 §5)."""

from __future__ import annotations

import json
import re
import shlex
import uuid
from collections.abc import AsyncIterator
from typing import Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from ..config.models import HostConfig
from ..config.store import load_global, load_user
from ..db.engine import _get_engine
from ..db.test_hosts import host_full_info
from ..devpod.host_exec import HostExecError, run_host_command, stream_host_command, write_host_file
from ..messages.renderer import build_deploy_context
from ..messages.service import delete_message as msg_delete
from ..messages.service import render_and_create
from .db import (
    create_deployment,
    delete_deployment,
    get_deployment,
    persist_op_log,
    update_deployment_message_id,
    update_deployment_status,
)
from .env_builder import render_env_file, resolve_env_values
from .models import ComposeDeployment, ComposeTemplate, DeploymentStatus
from .override_builder import build_override
from .port_aliases import parse_port_aliases, rewrite_compose_ports
from .ports import allocate_ports, check_ports

_log = structlog.get_logger(__name__)

_SECRET_REF_RE = re.compile(r"^\$\{(vault|env)://.+\}$")

_ROLE_MAP: dict[str, str] = {
    "portail": "portail",
    "workspaces": "workspace",
    "tests": "test",
}


class ComposeServiceError(Exception):
    """Erreur de cycle de vie d'un déploiement (FR)."""


def _remote_dir(name: str) -> str:
    return f"devpod-compose/{name}"


def _log_context_vars(host: HostConfig) -> dict[str, str]:
    """Variables de contexte injectées par le portail (LOKI_URL, HOSTNAME, MODULE, ROLE).

    Retourne un dict vide si logs.enabled=false ou si loki_push_url n'est pas configurée.
    """
    cfg = load_global()
    if not cfg.logs.enabled or not cfg.logs.loki_push_url:
        return {}
    return {
        "LOKI_URL": cfg.logs.loki_push_url,
        "MODULE": cfg.logs.module,
        "HOSTNAME": host.name,
        "ROLE": _ROLE_MAP.get(host.usage, "workspace"),
    }


def _host_for_node(node_id: str) -> HostConfig:
    host = next((h for h in load_global().hosts if h.name == node_id), None)
    if host is None:
        raise ComposeServiceError(f"nœud inconnu: {node_id}")
    if host.type != "ssh":
        raise ComposeServiceError(f"nœud {node_id}: type {host.type} non supporté (v1 ssh-only)")
    return host


def _validate_secret_refs(template: ComposeTemplate, env_values: dict[str, str]) -> None:
    for p in template.parameters:
        if p.type == "secret":
            val = env_values.get(p.key, "")
            if val and not _SECRET_REF_RE.fullmatch(val):
                raise ComposeServiceError(
                    f"paramètre secret {p.key!r} doit être une référence"
                    " ${vault://...} (valeur en clair refusée)"
                )


def _ports_from_env(template: ComposeTemplate, env_values: dict[str, str]) -> list[int]:
    ports: list[int] = []
    for p in template.parameters:
        if p.type == "port" and p.key in env_values:
            try:
                ports.append(int(env_values[p.key]))
            except ValueError as exc:
                raise ComposeServiceError(f"paramètre port {p.key} non entier") from exc
    return ports


def _parse_ps_status(ps_json: str) -> str:
    states: list[str] = []
    for line in ps_json.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            states.append(str(json.loads(line).get("State", "")))
        except json.JSONDecodeError:
            continue
    if not states:
        return "stopped"
    if all(s == "running" for s in states):
        return "running"
    if any(s == "running" for s in states):
        return "partial"
    return "stopped"


async def deploy(
    conn: AsyncConnection,
    *,
    name: str,
    template: ComposeTemplate,
    node_id: str,
    owner_login: str,
    secret_ns: str,
    env_values: dict[str, str],
) -> ComposeDeployment:
    host = _host_for_node(node_id)

    # Détection du mode d'allocation de ports.
    # Mode alias (chromium>3000:3000) : allocation automatique côté portail.
    # Mode classique (param type=port) : port fourni par l'utilisateur.
    aliases = parse_port_aliases(template.compose_content)
    if aliases:
        port_map = await allocate_ports(conn, host, node_id, aliases)
        host_ports = list(port_map.values())
        compose_to_write = rewrite_compose_ports(template.compose_content, port_map)
    else:
        port_map = {}
        host_ports = _ports_from_env(template, env_values)
        await check_ports(conn, host, node_id, host_ports)
        compose_to_write = template.compose_content

    _validate_secret_refs(template, env_values)

    resolved = resolve_env_values(owner_login, secret_ns, env_values)
    rdir = _remote_dir(name)

    try:
        await write_host_file(host, f"{rdir}/docker-compose.yml", compose_to_write)
        for fname, fcontent in template.extra_files.items():
            await write_host_file(host, f"{rdir}/{fname}", fcontent)
        await write_host_file(
            host, f"{rdir}/.env", render_env_file(resolved, _log_context_vars(host))
        )

        override_content = build_override(
            compose_to_write,
            deployment_id=name,
            template_id=template.id,
            owner_login=owner_login,
        )
        if override_content:
            await write_host_file(host, f"{rdir}/docker-compose.override.yml", override_content)

        cmd = (
            f"cd {shlex.quote(rdir)} && docker compose --env-file .env -p {shlex.quote(name)} up -d"
        )
        rc, out, err = await run_host_command(host, cmd, timeout=600.0)
    except HostExecError as exc:
        raise ComposeServiceError(str(exc)) from exc
    status: DeploymentStatus = "running" if rc == 0 else "error"

    uid = str(uuid.uuid4())
    dep = ComposeDeployment(
        uid=uid,
        id=name,
        template_id=template.id,
        template_version=template.version,
        node_id=node_id,
        owner_login=owner_login,
        env_values=env_values,  # références brutes, jamais les valeurs résolues
        host_ports=host_ports,
        status=status,
        last_error=None if rc == 0 else (err or out)[:2000],
    )
    await create_deployment(conn, dep)
    await persist_op_log(conn, uid, "up", out + ("\n" + err if err else ""))

    # Message contextuel pour les agents (non-bloquant, uniquement si déployé avec succès).
    if status == "running" and template.message_key:
        try:
            ws_info = await host_full_info(node_id, conn)
            if ws_info:
                ws_login, ws_name, ssh_alias = ws_info
                user_cfg = await load_user(ws_login)
                host_cfg = _host_for_node(node_id)
                ctx = build_deploy_context(
                    owner_login=ws_login,
                    workspace_name=ws_name,
                    host_name=node_id,
                    ssh_alias=ssh_alias,
                    host_address=host_cfg.address,
                    deployment_id=name,
                    template_name=template.name,
                    template_id=template.id,
                    template_description=template.description,
                    template_version=template.version,
                    template_tags=template.tags,
                    compose_content=template.compose_content,
                    port_map={str(i): p for i, p in enumerate(host_ports)},
                    culture=user_cfg.culture,
                )
                msg_id = await render_and_create(
                    conn,
                    key=template.message_key,
                    culture=user_cfg.culture,
                    owner_login=ws_login,
                    workspace_name=ws_name,
                    msg_type="compose_service",
                    ctx=ctx,
                )
                if msg_id is not None:
                    await update_deployment_message_id(conn, uid, msg_id)
                    dep = dep.model_copy(update={"message_id": msg_id})
        except Exception:
            _log.warning(
                "compose_deploy_message_create_failed",
                uid=uid,
                name=name,
                exc_info=True,
            )

    return dep


async def prepare_deployment(
    conn: AsyncConnection,
    *,
    template: ComposeTemplate,
    node_id: str,
    env_values: dict[str, str],
) -> tuple[dict[str, int], list[int], str]:
    """Alloue les ports et prépare le compose_content final.

    Retourne (port_map, host_ports, compose_to_write). Peut lever PortConflict ou
    ComposeServiceError — à appeler depuis un contexte DB avant de démarrer le streaming.
    """
    host = _host_for_node(node_id)
    aliases = parse_port_aliases(template.compose_content)
    if aliases:
        port_map = await allocate_ports(conn, host, node_id, aliases)
        host_ports = list(port_map.values())
        compose_to_write = rewrite_compose_ports(template.compose_content, port_map)
    else:
        port_map = {}
        host_ports = _ports_from_env(template, env_values)
        await check_ports(conn, host, node_id, host_ports)
        compose_to_write = template.compose_content
    return port_map, host_ports, compose_to_write


async def deploy_stream(
    *,
    name: str,
    template: ComposeTemplate,
    node_id: str,
    owner_login: str,
    secret_ns: str,
    env_values: dict[str, str],
    port_map: dict[str, int],
    host_ports: list[int],
    compose_to_write: str,
) -> AsyncIterator[str]:
    """Déploie en streamant la progression de docker compose up.

    Chaque ligne yieldée est une ligne de log texte. La dernière ligne est soit
    ``__RESULT__:{json}`` (succès) soit ``__ERROR__:{message}`` (échec).
    Les ports ont déjà été alloués par ``prepare_deployment``.
    """
    host = _host_for_node(node_id)
    _validate_secret_refs(template, env_values)
    resolved = resolve_env_values(owner_login, secret_ns, env_values)
    rdir = _remote_dir(name)

    try:
        await write_host_file(host, f"{rdir}/docker-compose.yml", compose_to_write)
        for fname, fcontent in template.extra_files.items():
            await write_host_file(host, f"{rdir}/{fname}", fcontent)
        await write_host_file(
            host, f"{rdir}/.env", render_env_file(resolved, _log_context_vars(host))
        )
        override_content = build_override(
            compose_to_write,
            deployment_id=name,
            template_id=template.id,
            owner_login=owner_login,
        )
        if override_content:
            await write_host_file(host, f"{rdir}/docker-compose.override.yml", override_content)
    except HostExecError as exc:
        raise ComposeServiceError(str(exc)) from exc

    yield "==> Fichiers docker-compose écrits\n"
    yield "==> Lancement de docker compose up -d...\n"

    cmd = (
        f"cd {shlex.quote(rdir)} && "
        f"docker compose --env-file .env --progress plain -p {shlex.quote(name)} up -d"
    )

    status: DeploymentStatus = "error"
    compose_out = ""
    last_err = ""
    try:
        async for line in stream_host_command(host, cmd, timeout=600.0):
            compose_out += line + "\n"
            yield line + "\n"
        status = "running"
    except HostExecError as exc:
        last_err = str(exc)
        status = "error"
        yield f"==> ERREUR : {last_err}\n"

    uid = str(uuid.uuid4())
    dep = ComposeDeployment(
        uid=uid,
        id=name,
        template_id=template.id,
        template_version=template.version,
        node_id=node_id,
        owner_login=owner_login,
        env_values=env_values,
        host_ports=host_ports,
        status=status,
        last_error=None if status == "running" else (last_err or compose_out)[:2000],
    )
    async with _get_engine().begin() as conn:
        await create_deployment(conn, dep)
        await persist_op_log(conn, uid, "up", compose_out)

    if status == "running" and template.message_key:
        try:
            async with _get_engine().begin() as conn:
                ws_info = await host_full_info(node_id, conn)
                if ws_info:
                    ws_login, ws_name, ssh_alias = ws_info
                    user_cfg = await load_user(ws_login)
                    host_cfg = _host_for_node(node_id)
                    ctx = build_deploy_context(
                        owner_login=ws_login,
                        workspace_name=ws_name,
                        host_name=node_id,
                        ssh_alias=ssh_alias,
                        host_address=host_cfg.address,
                        deployment_id=name,
                        template_name=template.name,
                        template_id=template.id,
                        template_description=template.description,
                        template_version=template.version,
                        template_tags=template.tags,
                        compose_content=template.compose_content,
                        port_map={str(i): p for i, p in enumerate(host_ports)},
                        culture=user_cfg.culture,
                    )
                    msg_id = await render_and_create(
                        conn,
                        key=template.message_key,
                        culture=user_cfg.culture,
                        owner_login=ws_login,
                        workspace_name=ws_name,
                        msg_type="compose_service",
                        ctx=ctx,
                    )
                    if msg_id is not None:
                        await update_deployment_message_id(conn, uid, msg_id)
                        dep = dep.model_copy(update={"message_id": msg_id})
        except Exception:
            _log.warning(
                "compose_deploy_stream_message_failed",
                uid=uid,
                name=name,
                exc_info=True,
            )

    if status == "error":
        yield f"__ERROR__:{last_err or 'docker compose up a échoué'}\n"
    else:
        yield f"__RESULT__:{dep.model_dump_json()}\n"


async def lifecycle(
    conn: AsyncConnection,
    uid: str,
    action: Literal["stop", "start", "restart"],
) -> None:
    dep = await get_deployment(conn, uid)
    if dep is None:
        raise ComposeServiceError(f"déploiement inconnu: {uid}")
    host = _host_for_node(dep.node_id)
    try:
        rc, out, err = await run_host_command(
            host, f"docker compose -p {shlex.quote(dep.id)} {action}", timeout=300.0
        )
    except HostExecError as exc:
        raise ComposeServiceError(str(exc)) from exc
    await persist_op_log(conn, uid, action, out + ("\n" + err if err else ""))
    if rc != 0:
        # rc≠0 → statut persisté en "error" et on retourne normalement (la row existe)
        await update_deployment_status(conn, uid, "error", (err or out)[:2000])
        return
    if action == "stop":
        await msg_delete(conn, dep.message_id)
        await update_deployment_message_id(conn, uid, None)
    await refresh_status(conn, uid)


async def teardown(conn: AsyncConnection, uid: str) -> None:
    dep = await get_deployment(conn, uid)
    if dep is None:
        raise ComposeServiceError(f"déploiement inconnu: {uid}")
    host = _host_for_node(dep.node_id)
    rdir = _remote_dir(dep.id)
    try:
        rc, out, err = await run_host_command(
            host,
            f"docker compose -p {shlex.quote(dep.id)} down -v ; rm -rf {shlex.quote(rdir)}",
            timeout=300.0,
        )
    except HostExecError as exc:
        raise ComposeServiceError(str(exc)) from exc
    await persist_op_log(conn, uid, "down", out + ("\n" + err if err else ""))
    if rc != 0:
        _log.warning("compose_teardown_failed", uid=uid, name=dep.id, rc=rc)
    await msg_delete(conn, dep.message_id)
    await delete_deployment(conn, uid)


async def fetch_logs(
    conn: AsyncConnection,
    uid: str,
    *,
    service: str | None,
    tail: int,
) -> str:
    dep = await get_deployment(conn, uid)
    if dep is None:
        raise ComposeServiceError(f"déploiement inconnu: {uid}")
    host = _host_for_node(dep.node_id)
    svc = f" {shlex.quote(service)}" if service else ""
    cmd = f"docker compose -p {shlex.quote(dep.id)} logs --no-color --tail={int(tail)}{svc}"
    try:
        _, out, err = await run_host_command(host, cmd, timeout=60.0)
    except HostExecError as exc:
        raise ComposeServiceError(str(exc)) from exc
    return out + ("\n" + err if err else "")


async def refresh_status(conn: AsyncConnection, uid: str) -> str:
    dep = await get_deployment(conn, uid)
    if dep is None:
        raise ComposeServiceError(f"déploiement inconnu: {uid}")
    host = _host_for_node(dep.node_id)
    try:
        rc, out, _ = await run_host_command(
            host,
            f"docker compose -p {shlex.quote(dep.id)} ps --format json",
            timeout=60.0,
        )
    except HostExecError as exc:
        raise ComposeServiceError(str(exc)) from exc
    status = _parse_ps_status(out) if rc == 0 else "error"
    await update_deployment_status(conn, uid, status)
    return status
