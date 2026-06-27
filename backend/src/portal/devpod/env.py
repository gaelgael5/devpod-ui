from __future__ import annotations

import os

import structlog

from ..config.models import GlobalConfig, HostConfig, WorkspaceSpec
from ..config.store import safe_user_path

_log = structlog.get_logger(__name__)


class UnknownHostError(ValueError):
    """L'host référencé n'existe pas dans la config globale."""


class HostNotReadyError(ValueError):
    """L'host existe mais n'est pas encore opérationnel (ex : clé SSH manquante)."""


def _find_host(host_name: str, global_cfg: GlobalConfig) -> HostConfig:
    """
    Retourne l'HostConfig correspondant, ou l'host par défaut si host_name est vide.
    Lève UnknownHostError si le nom est fourni mais inconnu.
    """
    if not host_name:
        defaults = [h for h in global_cfg.hosts if h.default]
        if not defaults:
            raise UnknownHostError("No default host configured")
        return defaults[0]
    for h in global_cfg.hosts:
        if h.name == host_name:
            return h
    raise UnknownHostError(f"Host {host_name!r} not found in global config")


def build_env(
    login: str,
    ws_spec: WorkspaceSpec,
    global_cfg: GlobalConfig,
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """
    Construit l'environnement subprocess pour un appel devpod.

    - DEVPOD_HOME : répertoire dédié au user (isolé par user)
    - DOCKER_HOST/DOCKER_TLS_VERIFY/DOCKER_CERT_PATH : pour host docker-tls uniquement
    - Pas de variables DOCKER_* pour host ssh
    """
    env: dict[str, str] = dict(os.environ if base_env is None else base_env)

    # DEVPOD_HOME isolé par user — construit via safe_user_path
    devpod_home = str(safe_user_path(login, "devpod"))
    env["DEVPOD_HOME"] = devpod_home

    host = _find_host(ws_spec.host, global_cfg)

    if host.type == "docker-tls":
        env["DOCKER_HOST"] = host.docker_host
        env["DOCKER_TLS_VERIFY"] = "1"
        env["DOCKER_CERT_PATH"] = global_cfg.devpod.client_cert_path
        _log.debug("devpod_env_docker_tls", login=login, docker_host=host.docker_host)
    else:
        # SSH : DevPod gère la connexion, supprimer les DOCKER_* si présents
        env.pop("DOCKER_HOST", None)
        env.pop("DOCKER_TLS_VERIFY", None)
        env.pop("DOCKER_CERT_PATH", None)
        _log.debug("devpod_env_ssh", login=login, address=host.address)

    return env
