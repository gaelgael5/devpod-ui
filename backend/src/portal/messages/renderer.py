"""Rendu Jinja2 sandboxé + constructeurs de contexte."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from jinja2.sandbox import SandboxedEnvironment

_log = structlog.get_logger(__name__)

_env = SandboxedEnvironment(
    autoescape=False,
    keep_trailing_newline=True,
)


def render(template_body: str, ctx: dict[str, Any]) -> str:
    """Rend un template Jinja2 avec le contexte donné.

    Lève ValueError si le template est invalide ou le rendu échoue.
    """
    tpl = _env.from_string(template_body)
    return tpl.render(**ctx)


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def _extract_ip(address: str) -> str:
    """Extrait l'IP/hostname depuis 'user@host' ou retourne address tel quel."""
    return address.split("@", 1)[-1] if "@" in address else address


def build_host_context(
    *,
    owner_login: str,
    workspace_name: str,
    host_name: str,
    alias: str,
    address: str,
    culture: str,
) -> dict[str, Any]:
    ip = _extract_ip(address)
    parts = address.split("@", 1)
    ssh_user = parts[0] if len(parts) == 2 else "root"
    return {
        "host": {
            "name": host_name,
            "ssh_alias": alias,
            "ip": ip,
            "ssh_user": ssh_user,
            "ssh_port": 22,
        },
        "workspace": {
            "id": workspace_name,
            "owner": owner_login,
        },
        "user": {
            "login": owner_login,
            "culture": culture,
        },
        "created_at": _now_iso(),
    }


def build_deploy_context(
    *,
    owner_login: str,
    workspace_name: str,
    host_name: str,
    ssh_alias: str,
    host_address: str,
    deployment_id: str,
    template_name: str,
    template_id: str,
    template_description: str,
    template_version: str,
    template_tags: list[str],
    compose_content: str,
    port_map: dict[str, int],
    culture: str,
) -> dict[str, Any]:
    import yaml as _yaml

    ip = _extract_ip(host_address)
    parts = host_address.split("@", 1)
    ssh_user = parts[0] if len(parts) == 2 else "root"

    try:
        compose_parsed = _yaml.safe_load(compose_content) or {}
    except Exception:
        compose_parsed = {}

    return {
        "host": {
            "name": host_name,
            "ssh_alias": ssh_alias,
            "ip": ip,
            "ssh_user": ssh_user,
            "ssh_port": 22,
        },
        "deployment": {
            "id": deployment_id,
            "status": "running",
            "ports": port_map,
            "template": {
                "id": template_id,
                "name": template_name,
                "description": template_description,
                "version": template_version,
                "tags": template_tags,
            },
            "compose": compose_parsed,
        },
        "workspace": {
            "id": workspace_name,
            "owner": owner_login,
        },
        "user": {
            "login": owner_login,
            "culture": culture,
        },
        "started_at": _now_iso(),
    }
