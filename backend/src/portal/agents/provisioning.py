"""Intégration des agents workspace dans le provisioning (spec 35 §4.3, §5).

Produit, pour un workspace dont le spec demande des agents :
- la rotation des clefs (une par profil exposé) ;
- l'arborescence agent-config stagée localement puis poussée sur le host SSH ;
- le bind mount read-only et les commandes postCreate (symlinks + exclusion git)
  à injecter dans le devcontainer.json.

Le rendu des target_path passe par le même sandbox Jinja que les contenus, avec
`home` = « $HOME » littéral : le chemin est résolu par le shell postCreate en tant
qu'utilisateur du conteneur (le portail ne connaît pas le home de l'image).
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from ..config.store import safe_user_path
from .keys import rotate_workspace_keys
from .models import AGENT_ID_RE, validate_filename
from .renderer import AgentRenderError, build_render_context, render_agent_file
from .sync import AGENT_CONFIG_ROOT, push_tree_ssh, resolve_remote_home
from .tree import WS_ID_RE, generate_workspace_tree

_log = structlog.get_logger(__name__)

AGENT_MOUNT_TARGET = "/opt/agent-config"


class AgentProvisionError(ValueError):
    """Erreur de provisioning agents — remontée en 422 par les routes."""


@dataclass(frozen=True)
class AgentSetup:
    """Fragments à injecter dans le devcontainer.json."""

    mounts: list[str]
    post_create: list[str]


def build_agent_mount(remote_home: str, ws_id: str) -> str:
    if not remote_home.startswith("/"):
        raise AgentProvisionError(f"home distant invalide : {remote_home!r}")
    if not WS_ID_RE.fullmatch(ws_id):
        raise AgentProvisionError(f"ws_id invalide : {ws_id!r}")
    source = f"{remote_home}/{AGENT_CONFIG_ROOT}/{ws_id}"
    return f"source={source},target={AGENT_MOUNT_TARGET},type=bind,readonly"


def _render_target(agent: dict[str, Any], project_root: str, workspace: dict[str, str]) -> str:
    try:
        target = render_agent_file(
            str(agent["target_path"]),
            {"home": "$HOME", "project_root": project_root, "workspace": workspace},
        )
    except AgentRenderError as exc:
        raise AgentProvisionError(f"agent '{agent['id']}' : target_path — {exc}") from exc
    if not (target.startswith("/") or target.startswith("$HOME/")):
        raise AgentProvisionError(
            f"agent '{agent['id']}' : target_path doit être absolu ({target!r})"
        )
    # Le target est interpolé entre double quotes dans postCreateCommand : aucun
    # métacaractère shell, et '$' uniquement via le préfixe $HOME.
    forbidden = set("\"'`;\\\n")
    if ".." in target.split("/") or forbidden & set(target) or "$" in target.removeprefix("$HOME"):
        raise AgentProvisionError(
            f"agent '{agent['id']}' : target_path rendu invalide ({target!r})"
        )
    return target


def build_agent_post_create(
    agents: list[dict[str, Any]],
    *,
    project_root: str,
    workspace: dict[str, str] | None = None,
) -> list[str]:
    """Commandes postCreate : symlink par agent + exclusion git locale si le
    target tombe dans le repo (jamais le .gitignore versionné)."""
    ws_meta = workspace or {}
    cmds: list[str] = []
    for agent in agents:
        agent_id = str(agent["id"])
        if not AGENT_ID_RE.fullmatch(agent_id):
            raise AgentProvisionError(f"agent id invalide : {agent_id!r}")
        try:
            filename = validate_filename(str(agent["filename"]))
        except ValueError as exc:
            raise AgentProvisionError(str(exc)) from exc
        target = _render_target(agent, project_root, ws_meta)
        link = f"{AGENT_MOUNT_TARGET}/{agent_id}/{filename}"
        cmds.append(f'mkdir -p "$(dirname "{target}")" && ln -sfn "{link}" "{target}"')
        if target.startswith(f"{project_root}/"):
            rel = "/" + target.removeprefix(f"{project_root}/")
            exclude = f"{project_root}/.git/info/exclude"
            cmds.append(
                f'if [ -d "{project_root}/.git" ]; then '
                f'mkdir -p "{project_root}/.git/info" && '
                f'{{ grep -qxF "{rel}" "{exclude}" 2>/dev/null || '
                f'printf \'%s\\n\' "{rel}" >> "{exclude}"; }}; fi'
            )
    return cmds


async def _load_requested_agent_types(agents: list[str]) -> list[dict[str, Any]]:
    from ..db.agent_types import list_agent_types
    from ..db.engine import _get_engine

    async with _get_engine().connect() as conn:
        available = {row["id"]: row for row in await list_agent_types(conn)}
    rows: list[dict[str, Any]] = []
    for aid in agents:
        row = available.get(aid)
        if row is None:
            raise AgentProvisionError(f"type d'agent inconnu : {aid!r}")
        if not row["enabled"]:
            raise AgentProvisionError(f"type d'agent désactivé : {aid!r}")
        rows.append(row)
    return rows


async def prepare_workspace_agents(
    *,
    login: str,
    ws_id: str,
    ws_name: str,
    agents: list[str],
    host_type: str,
    ssh_user: str,
    ssh_host: str,
    ssh_key_path: str,
    mcp_url: str,
    project_root: str,
) -> AgentSetup:
    """Prépare l'accès MCP des agents d'un workspace (appelé par DevPodService.up).

    Lève AgentProvisionError (422) si un agent est inconnu/désactivé ou si le host
    ne permet pas la dépose des fichiers (docker-tls : hors périmètre v1, spec 35 §10).
    """
    if host_type != "ssh":
        raise AgentProvisionError(
            f"agents non disponibles sur un host '{host_type}' : la dépose des fichiers "
            "de configuration requiert un host SSH (spec 35 §10, v1)"
        )
    if not (ssh_host and ssh_key_path):
        raise AgentProvisionError("host SSH incomplet (adresse ou clé manquante)")

    agent_rows = await _load_requested_agent_types(agents)

    from ..db.engine import _get_engine

    async with _get_engine().begin() as conn:
        keys = await rotate_workspace_keys(conn, login, ws_id)

    context = build_render_context(
        keys=keys,
        mcp_url=mcp_url,
        ws_id=ws_id,
        workspace_name=ws_name,
        owner_login=login,
        home="$HOME",
        project_root=project_root,
    )

    staging_root = safe_user_path(login, "devpod")
    staging_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=staging_root, prefix=f"{ws_id}-agents-"))
    try:
        try:
            ws_dir = generate_workspace_tree(staging, ws_id, agent_rows, context)
        except Exception as exc:
            raise AgentProvisionError(str(exc)) from exc
        remote_home = await resolve_remote_home(ssh_user, ssh_host, ssh_key_path)
        await push_tree_ssh(
            ws_dir,
            [row["id"] for row in agent_rows],
            ssh_user=ssh_user,
            ssh_host=ssh_host,
            ssh_key_path=ssh_key_path,
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    workspace_meta = {"id": ws_id, "name": ws_name, "owner": login}
    setup = AgentSetup(
        mounts=[build_agent_mount(remote_home, ws_id)],
        post_create=build_agent_post_create(
            agent_rows, project_root=project_root, workspace=workspace_meta
        ),
    )
    _log.info(
        "workspace_agents_prepared",
        ws_id=ws_id,
        agents=[row["id"] for row in agent_rows],
        profiles=[k.profile_id for k in keys],
    )
    return setup
