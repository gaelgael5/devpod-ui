"""Orchestration du cycle de vie d'un déploiement compose (spec 26 §5)."""
from __future__ import annotations

import json
import shlex
from typing import Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from ..config.models import HostConfig
from ..config.store import load_global
from ..devpod.host_exec import run_host_command, write_host_file
from .db import (
    create_deployment,
    delete_deployment,
    get_deployment,
    persist_op_log,
    update_deployment_status,
)
from .env_builder import render_env_file, resolve_env_values
from .models import ComposeDeployment, ComposeTemplate, DeploymentStatus
from .ports import check_ports

_log = structlog.get_logger(__name__)


class ComposeServiceError(Exception):
    """Erreur de cycle de vie d'un déploiement (FR)."""


def _remote_dir(deployment_id: str) -> str:
    return f"devpod-compose/{deployment_id}"


def _host_for_node(node_id: str) -> HostConfig:
    host = next((h for h in load_global().hosts if h.name == node_id), None)
    if host is None:
        raise ComposeServiceError(f"nœud inconnu: {node_id}")
    if host.type != "ssh":
        raise ComposeServiceError(f"nœud {node_id}: type {host.type} non supporté (v1 ssh-only)")
    return host


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
    deployment_id: str,
    template: ComposeTemplate,
    node_id: str,
    owner_login: str,
    secret_ns: str,
    env_values: dict[str, str],
) -> ComposeDeployment:
    host = _host_for_node(node_id)
    host_ports = _ports_from_env(template, env_values)
    await check_ports(conn, host, node_id, host_ports)

    resolved = resolve_env_values(owner_login, secret_ns, env_values)  # en mémoire uniquement
    rdir = _remote_dir(deployment_id)
    await write_host_file(host, f"{rdir}/docker-compose.yml", template.compose_content)
    await write_host_file(host, f"{rdir}/.env", render_env_file(resolved))

    cmd = (
        f"cd {shlex.quote(rdir)} && "
        f"docker compose --env-file .env -p {shlex.quote(deployment_id)} up -d"
    )
    rc, out, err = await run_host_command(host, cmd, timeout=600.0)
    status: DeploymentStatus = "running" if rc == 0 else "error"

    dep = ComposeDeployment(
        id=deployment_id,
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
    await persist_op_log(conn, deployment_id, "up", out + ("\n" + err if err else ""))
    # rc≠0 → la row est persistée (teardown peut nettoyer) ; on retourne le dep avec status="error"
    return dep


async def lifecycle(
    conn: AsyncConnection,
    deployment_id: str,
    action: Literal["stop", "start", "restart"],
) -> None:
    dep = await get_deployment(conn, deployment_id)
    if dep is None:
        raise ComposeServiceError(f"déploiement inconnu: {deployment_id}")
    host = _host_for_node(dep.node_id)
    rc, out, err = await run_host_command(
        host, f"docker compose -p {shlex.quote(deployment_id)} {action}", timeout=300.0
    )
    await persist_op_log(conn, deployment_id, action, out + ("\n" + err if err else ""))
    if rc != 0:
        # rc≠0 → statut persisté en "error" et on retourne normalement (la row existe)
        await update_deployment_status(conn, deployment_id, "error", (err or out)[:2000])
        return
    await refresh_status(conn, deployment_id)


async def teardown(conn: AsyncConnection, deployment_id: str) -> None:
    dep = await get_deployment(conn, deployment_id)
    if dep is None:
        raise ComposeServiceError(f"déploiement inconnu: {deployment_id}")
    host = _host_for_node(dep.node_id)
    rdir = _remote_dir(deployment_id)
    rc, out, err = await run_host_command(
        host,
        f"docker compose -p {shlex.quote(deployment_id)} down -v ; rm -rf {shlex.quote(rdir)}",
        timeout=300.0,
    )
    await persist_op_log(conn, deployment_id, "down", out + ("\n" + err if err else ""))
    if rc != 0:
        _log.warning("compose_teardown_failed", deployment_id=deployment_id, rc=rc)
    await delete_deployment(conn, deployment_id)


async def fetch_logs(
    conn: AsyncConnection,
    deployment_id: str,
    *,
    service: str | None,
    tail: int,
) -> str:
    dep = await get_deployment(conn, deployment_id)
    if dep is None:
        raise ComposeServiceError(f"déploiement inconnu: {deployment_id}")
    host = _host_for_node(dep.node_id)
    svc = f" {shlex.quote(service)}" if service else ""
    cmd = (
        f"docker compose -p {shlex.quote(deployment_id)} logs --no-color "
        f"--tail={int(tail)}{svc}"
    )
    _, out, err = await run_host_command(host, cmd, timeout=60.0)
    return out + ("\n" + err if err else "")


async def refresh_status(conn: AsyncConnection, deployment_id: str) -> str:
    dep = await get_deployment(conn, deployment_id)
    if dep is None:
        raise ComposeServiceError(f"déploiement inconnu: {deployment_id}")
    host = _host_for_node(dep.node_id)
    rc, out, _ = await run_host_command(
        host,
        f"docker compose -p {shlex.quote(deployment_id)} ps --format json",
        timeout=60.0,
    )
    status = _parse_ps_status(out) if rc == 0 else "error"
    await update_deployment_status(conn, deployment_id, status)
    return status
