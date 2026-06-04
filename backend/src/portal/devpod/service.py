from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import structlog

from ..config.models import GlobalConfig, WorkspaceSpec
from ..config.store import _data_root, safe_user_path
from .env import build_env
from .provider import ensure_provider
from .runner import run_subprocess

_log = structlog.get_logger(__name__)

# DNS-safe pour ws_id : login (max ~40 chars) + "-" + name (max 32 chars)
_WS_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$")


class DevPodService:
    def __init__(
        self,
        global_cfg: GlobalConfig,
        devpod_bin: list[str] | None = None,
    ) -> None:
        self._global_cfg = global_cfg
        self._devpod_bin: list[str] = (
            devpod_bin if devpod_bin is not None else [global_cfg.devpod.binary]
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def _ws_id(self, login: str, name: str) -> str:
        """Construit et valide le ws_id DNS-safe."""
        ws_id = f"{login}-{name}"
        if not _WS_ID_RE.fullmatch(ws_id):
            raise ValueError(f"Computed ws_id {ws_id!r} is not DNS-safe")
        return ws_id

    async def up(self, login: str, ws_spec: WorkspaceSpec) -> str:
        """Lance un workspace en tâche de fond. Retourne ws_id immédiatement."""
        ws_id = self._ws_id(login, ws_spec.name)

        # Env de base (DEVPOD_HOME, DOCKER_*) — sans les secrets utilisateur
        base_env = build_env(login=login, ws_spec=ws_spec, global_cfg=self._global_cfg)

        host_type = self._resolve_host_type(ws_spec)
        await ensure_provider(
            login=login,
            host_type=host_type,
            env=base_env,
            devpod_bin=self._devpod_bin,
        )

        dc_path = self._write_devcontainer(login, ws_id)

        # Les env vars utilisateur (secrets) sont fusionnées ici, injectées dans
        # le subprocess env UNIQUEMENT — jamais dans devcontainer.json ni dans les logs.
        subprocess_env = {**base_env, **ws_spec.env}

        self._write_status(ws_id, "provisioning", login=login)

        asyncio.create_task(
            self._run_up_task(ws_id, ws_spec.source, dc_path, subprocess_env, login)
        )
        _log.info("workspace_up_started", ws_id=ws_id, login=login)
        return ws_id

    async def stop(self, login: str, ws_id: str) -> None:
        """Arrête un workspace en cours d'exécution."""
        env = self._minimal_env(login)
        cmd = [*self._devpod_bin, "stop", ws_id]
        log_path = self._log_path(login, f"{ws_id}-stop")
        await run_subprocess(cmd=cmd, env=env, log_path=log_path, ws_id=ws_id)
        self._write_status(ws_id, "stopped")
        _log.info("workspace_stopped", ws_id=ws_id, login=login)

    async def delete(self, login: str, ws_id: str) -> None:
        """Supprime un workspace (force)."""
        env = self._minimal_env(login)
        cmd = [*self._devpod_bin, "delete", ws_id, "--force"]
        log_path = self._log_path(login, f"{ws_id}-delete")
        await run_subprocess(cmd=cmd, env=env, log_path=log_path, ws_id=ws_id)
        status_path = self._status_path(ws_id)
        if status_path.exists():
            status_path.unlink()
        _log.info("workspace_deleted", ws_id=ws_id, login=login)

    async def status(self, login: str, ws_id: str) -> dict[str, Any]:
        """Retourne l'état courant depuis le fichier de statut."""
        path = self._status_path(ws_id)
        if not path.exists():
            return {"ws_id": ws_id, "status": "unknown"}
        return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]

    async def list_workspaces(self, login: str) -> list[dict[str, Any]]:
        """Liste les workspaces du user depuis les fichiers de statut."""
        routes_dir = _data_root() / "routes"
        if not routes_dir.exists():
            return []
        results: list[dict[str, Any]] = []
        for f in routes_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("login") == login:
                    results.append(data)
            except json.JSONDecodeError:
                pass
        return results

    def get_port(self, ws_id: str) -> int | None:
        """Stub — implémentation propre en M6."""
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _status_path(self, ws_id: str) -> Path:
        return _data_root() / "routes" / f"{ws_id}.json"

    def _log_path(self, login: str, ws_id: str) -> Path:
        return _data_root() / "logs" / login / f"{ws_id}.log"

    def _write_status(self, ws_id: str, status: str, login: str = "", **extra: Any) -> None:
        """Écrit atomiquement le fichier de statut."""
        path = self._status_path(ws_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {"ws_id": ws_id, "status": status}
        if login:
            data["login"] = login
        data.update(extra)
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=f"-{ws_id}.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp_path, path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    def _write_devcontainer(self, login: str, ws_id: str) -> Path:
        """Écrit un devcontainer.json minimal dans le dossier user (recipes = M7)."""
        user_dir = safe_user_path(login, "devpod")
        user_dir.mkdir(parents=True, exist_ok=True)
        content = {
            "image": "mcr.microsoft.com/devcontainers/base:ubuntu",
        }
        fd, tmp_path = tempfile.mkstemp(dir=user_dir, suffix=f"-{ws_id}.json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(content, f, indent=2)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
        return Path(tmp_path)

    def _resolve_host_type(self, ws_spec: WorkspaceSpec) -> str:
        """Résout le type d'host à partir de la spec workspace."""
        host_name = ws_spec.host
        if not host_name:
            defaults = [h for h in self._global_cfg.hosts if h.default]
            return defaults[0].type if defaults else "docker-tls"
        for h in self._global_cfg.hosts:
            if h.name == host_name:
                return h.type
        return "docker-tls"

    def _minimal_env(self, login: str) -> dict[str, str]:
        """Env minimal pour les commandes stop/delete (pas de secrets)."""
        return {
            "PATH": os.environ.get("PATH", ""),
            "DEVPOD_HOME": str(safe_user_path(login, "devpod")),
        }

    async def _run_up_task(
        self,
        ws_id: str,
        source: str,
        dc_path: Path,
        env: dict[str, str],
        login: str,
    ) -> None:
        """Tâche de fond : exécute devpod up et met à jour le statut."""
        try:
            cmd = [
                *self._devpod_bin,
                "up",
                source,
                "--id",
                ws_id,
                "--ide",
                "openvscode",
                "--devcontainer-path",
                str(dc_path),
                "--open-ide=false",  # v0.6.15 : empêche l'ouverture auto du navigateur
            ]
            log_path = self._log_path(login, ws_id)
            # Seul le returncode est logué — la valeur des env vars (secrets) n'est jamais écrite
            returncode = await run_subprocess(cmd=cmd, env=env, log_path=log_path, ws_id=ws_id)
            status = "running" if returncode == 0 else "failed"
            self._write_status(ws_id, status, login=login, returncode=returncode)
            if returncode != 0:
                _log.warning("workspace_up_failed", ws_id=ws_id, returncode=returncode)
            else:
                _log.info("workspace_up_done", ws_id=ws_id, login=login)
        except Exception as exc:
            self._write_status(ws_id, "failed", login=login, error=type(exc).__name__)
            _log.error("workspace_up_crashed", ws_id=ws_id, error=type(exc).__name__)
        finally:
            with contextlib.suppress(OSError):
                dc_path.unlink()
