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
from ..events.bus import emit_event
from ..messages.renderer import build_deploy_context
from ..messages.service import delete_message as msg_delete
from ..messages.service import render_and_create
from .db import (
    acquire_node_ports_lock,
    create_deployment,
    delete_deployment,
    get_deployment,
    get_deployment_by_name_node,
    get_template,
    list_auto_start_for_user,
    persist_op_log,
    update_deployment_message_id,
    update_deployment_status,
)
from .env_builder import render_env_file, resolve_env_values
from .models import ComposeDeployment, ComposeTemplate, DeploymentStatus
from .override_builder import build_override
from .port_aliases import parse_port_aliases, rewrite_compose_ports
from .ports import PortConflict, allocate_ports, check_ports

_log = structlog.get_logger(__name__)

# Côté compose, seul ${vault://...} (isolé par secret_ns) est une référence de
# secret légitime. ${env://...} est refusé : il permettrait de lire n'importe
# quelle variable du process portail (bug 002).
_SECRET_REF_RE = re.compile(r"^\$\{vault://.+\}$")

# Spec 33 : "ressources" = service partagé permanent, sans workspace propriétaire.
_ROLE_MAP: dict[str, str] = {
    "portail": "portail",
    "workspaces": "workspace",
    "tests": "test",
    "ressources": "ressource",
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


def foreign_env_keys(template: ComposeTemplate, env_values: dict[str, str]) -> list[str]:
    """Clés de `env_values` non déclarées comme paramètres du template.

    Toute clé étrangère est un vecteur d'injection : le contrat est que l'utilisateur
    ne renseigne QUE les paramètres exposés par le template (bug 002).
    """
    declared = {p.key for p in template.parameters}
    return sorted(k for k in env_values if k not in declared)


def _reject_foreign_env_keys(template: ComposeTemplate, env_values: dict[str, str]) -> None:
    foreign = foreign_env_keys(template, env_values)
    if foreign:
        raise ComposeServiceError(
            f"clés env_values non déclarées par le template: {foreign}"
        )


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
    _reject_foreign_env_keys(template, env_values)
    _validate_secret_refs(template, env_values)

    # Réservation précoce (bug 015) : l'allocation et l'INSERT de la ligne
    # « created » (porteuse des host_ports) se font dans une transaction courte
    # dédiée, sérialisée par nœud via le verrou advisory — un déploiement
    # concurrent ne lit used_ports_on_node qu'après le COMMIT de cette
    # réservation. Sans cela, la ligne n'apparaissait qu'après docker compose up
    # (jusqu'à 600 s) et deux déploiements recevaient le même port.
    #
    # Détection du mode d'allocation de ports.
    # Mode alias (chromium>3000:3000) : allocation automatique côté portail.
    # Mode classique (param type=port) : port fourni par l'utilisateur.
    aliases = parse_port_aliases(template.compose_content)
    uid = str(uuid.uuid4())
    async with _get_engine().begin() as res_conn:
        await acquire_node_ports_lock(res_conn, node_id)
        if await get_deployment_by_name_node(res_conn, name, node_id) is not None:
            raise ComposeServiceError(f"déploiement {name!r} existe déjà sur ce nœud")
        if aliases:
            port_map = await allocate_ports(res_conn, host, node_id, aliases)
            host_ports = list(port_map.values())
            compose_to_write = rewrite_compose_ports(template.compose_content, port_map)
        else:
            port_map = {}
            host_ports = _ports_from_env(template, env_values)
            await check_ports(res_conn, host, node_id, host_ports)
            compose_to_write = template.compose_content
        await create_deployment(
            res_conn,
            ComposeDeployment(
                uid=uid,
                id=name,
                template_id=template.id,
                template_version=template.version,
                node_id=node_id,
                owner_login=owner_login,
                env_values=env_values,  # références brutes, jamais les valeurs résolues
                host_ports=host_ports,
                status="created",
                last_error=None,
            ),
        )

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
        # Rien n'a pu être exécuté : la réservation est retirée — même état
        # final qu'avant (aucune ligne), l'auto-start peut retenter plus tard.
        async with _get_engine().begin() as err_conn:
            await delete_deployment(err_conn, uid)
        raise ComposeServiceError(str(exc)) from exc
    status: DeploymentStatus = "running" if rc == 0 else "error"

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
        last_error=None if rc == 0 else (err or out)[:2000],
    )
    await update_deployment_status(conn, uid, status, dep.last_error)
    await persist_op_log(conn, uid, "up", out + ("\n" + err if err else ""))
    if status == "running":
        await emit_event(
            "compose_service.started",
            actor=owner_login,
            subject=_event_subject(uid, name, template.id, node_id, "up"),
        )

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
    name: str,
    template: ComposeTemplate,
    node_id: str,
    owner_login: str,
    env_values: dict[str, str],
) -> tuple[str, dict[str, int], list[int], str]:
    """Alloue les ports et RÉSERVE le déploiement (ligne « created », bug 015).

    L'allocation lit used_ports_on_node sous verrou advisory par nœud, et la
    ligne de réservation (porteuse des host_ports) est insérée dans la même
    transaction : dès le COMMIT du caller, un déploiement concurrent voit les
    ports pris. Sans cela, la ligne n'apparaissait qu'à la fin de deploy_stream,
    jusqu'à 600 s plus tard — deux déploiements recevaient le même port.

    Retourne (uid, port_map, host_ports, compose_to_write). Peut lever
    PortConflict ou ComposeServiceError — à appeler depuis un contexte DB
    avant de démarrer le streaming.
    """
    host = _host_for_node(node_id)
    _reject_foreign_env_keys(template, env_values)
    await acquire_node_ports_lock(conn, node_id)
    if await get_deployment_by_name_node(conn, name, node_id) is not None:
        raise ComposeServiceError(f"déploiement {name!r} existe déjà sur ce nœud")
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
    uid = str(uuid.uuid4())
    await create_deployment(
        conn,
        ComposeDeployment(
            uid=uid,
            id=name,
            template_id=template.id,
            template_version=template.version,
            node_id=node_id,
            owner_login=owner_login,
            env_values=env_values,
            host_ports=host_ports,
            status="created",
            last_error=None,
        ),
    )
    return uid, port_map, host_ports, compose_to_write


async def deploy_stream(
    *,
    uid: str,
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
    Les ports ont déjà été alloués et réservés par ``prepare_deployment``
    (ligne « created » d'uid ``uid``, bug 015) — ici on finalise cette ligne.
    """
    host = _host_for_node(node_id)
    _reject_foreign_env_keys(template, env_values)
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
        # Rien n'a pu être exécuté : la réservation est retirée — même état
        # final qu'avant (aucune ligne), le nom et les ports redeviennent libres.
        async with _get_engine().begin() as err_conn:
            await delete_deployment(err_conn, uid)
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
        # Finalise la ligne de réservation insérée par prepare_deployment (bug 015).
        await update_deployment_status(conn, uid, status, dep.last_error)
        await persist_op_log(conn, uid, "up", compose_out)
    if status == "running":
        await emit_event(
            "compose_service.started",
            actor=owner_login,
            subject=_event_subject(uid, name, template.id, node_id, "up"),
        )

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


def _event_subject(
    uid: str, deployment_id: str, template_id: str, node_id: str, action: str
) -> dict[str, str]:
    return {
        "deployment_uid": uid,
        "deployment_id": deployment_id,
        "template_id": template_id,
        "node_id": node_id,
        "action": action,
    }


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
    await emit_event(
        "compose_service.stopped" if action == "stop" else "compose_service.started",
        actor=dep.owner_login,
        subject=_event_subject(uid, dep.id, dep.template_id, dep.node_id, action),
    )


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
    await emit_event(
        "compose_service.stopped",
        actor=dep.owner_login,
        subject=_event_subject(uid, dep.id, dep.template_id, dep.node_id, "down"),
    )


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


async def deploy_auto_start_templates(
    conn: AsyncConnection, *, owner_login: str, secret_ns: str, node_id: str
) -> AsyncIterator[str]:
    """Déploie sur `node_id` les templates cochés auto-start par `owner_login`.

    Best-effort : une entrée en échec (port, validation, exécution SSH) est journalisée
    et n'empêche pas les suivantes. Ne redéploie jamais un template déjà présent sur ce
    nœud (cadrage utilisateur : idempotence = ne rien faire si ça existe déjà).
    """
    entries = await list_auto_start_for_user(conn, owner_login)
    if not entries:
        return
    for entry in entries:
        if await get_deployment_by_name_node(conn, entry.template_id, node_id) is not None:
            continue
        tpl = await get_template(conn, entry.template_id)
        if tpl is None:
            _log.warning("auto_start_template_missing", template_id=entry.template_id)
            continue
        yield f"==> Auto-start : déploiement de {tpl.name}...\n"
        try:
            await deploy(
                conn,
                name=entry.template_id,
                template=tpl,
                node_id=node_id,
                owner_login=owner_login,
                secret_ns=secret_ns,
                env_values=entry.env_values,
            )
        except (ComposeServiceError, PortConflict) as exc:
            _log.warning(
                "auto_start_deploy_failed",
                template_id=entry.template_id,
                node_id=node_id,
                exc=repr(exc),
            )
            yield f"==> AVERTISSEMENT : auto-start {tpl.name} échoué ({exc})\n"
            continue
        yield f"==> {tpl.name} démarré (auto-start)\n"
