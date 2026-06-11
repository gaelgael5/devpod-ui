from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import structlog

from ..config.models import GlobalConfig, SourceSpec, WorkspaceSpec
from ..config.store import _data_root, safe_user_path
from ..recipes.models import RecipeMeta
from .env import _find_host, build_env
from .provider import ensure_provider
from .runner import run_subprocess

if TYPE_CHECKING:
    from ..exposure import ExposureService

_log = structlog.get_logger(__name__)

_RECIPES_BUILTIN_DIR = Path(__file__).parent.parent / "recipes" / "builtin"

# DNS-safe pour ws_id : login (max ~40 chars) + "-" + name (max 32 chars)
_WS_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$")


def _repo_name_from_url(url: str) -> str:
    """Dérive un nom de répertoire safe depuis une URL git."""
    base = url.rstrip("/").split("/")[-1]
    if base.endswith(".git"):
        base = base[:-4]
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", base)
    return safe or "repo"


class DevPodService:
    def __init__(
        self,
        global_cfg: GlobalConfig,
        devpod_bin: list[str] | None = None,
        exposure: ExposureService | None = None,
        recipes_builtin_dir: Path | None = None,
    ) -> None:
        self._global_cfg = global_cfg
        self._devpod_bin: list[str] = (
            devpod_bin if devpod_bin is not None else [global_cfg.devpod.binary]
        )
        self._exposure = exposure
        self._recipes_builtin_dir: Path = (
            recipes_builtin_dir if recipes_builtin_dir is not None else _RECIPES_BUILTIN_DIR
        )
        self._background_tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def _ws_id(self, login: str, name: str) -> str:
        """Construit et valide le ws_id DNS-safe."""
        ws_id = f"{login}-{name}"
        if not _WS_ID_RE.fullmatch(ws_id):
            raise ValueError(f"Computed ws_id {ws_id!r} is not DNS-safe")
        return ws_id

    async def up(
        self,
        login: str,
        ws_spec: WorkspaceSpec,
        recipes: list[RecipeMeta] | None = None,
        feature_env: dict[str, str] | None = None,
    ) -> str:
        """Lance un workspace en tâche de fond. Retourne ws_id immédiatement."""
        ws_id = self._ws_id(login, ws_spec.name)

        # Env de base (DEVPOD_HOME, DOCKER_*) — sans les secrets utilisateur
        base_env = build_env(login=login, ws_spec=ws_spec, global_cfg=self._global_cfg)

        # Résoudre le host pour extraire les infos SSH si nécessaire
        host_cfg = _find_host(ws_spec.host, self._global_cfg)
        ssh_host = ""
        ssh_user = "root"
        if host_cfg.type == "ssh" and host_cfg.address:
            if "@" in host_cfg.address:
                ssh_user, ssh_host = host_cfg.address.split("@", 1)
            else:
                ssh_host = host_cfg.address

        provider_name = await ensure_provider(
            login=login,
            host_type=host_cfg.type,
            env=base_env,
            host_name=host_cfg.name,
            ssh_host=ssh_host,
            ssh_user=ssh_user,
            devpod_bin=self._devpod_bin,
        )

        host_port: int | None = None
        if self._exposure is not None:
            host_port = await self._exposure.allocate_port(ws_id)

        dc_path = self._write_devcontainer(
            login, ws_id,
            host_port=host_port,
            recipes=recipes,
            feature_env=feature_env,
            extra_sources=ws_spec.extra_sources if ws_spec.extra_sources else None,
        )

        # Les env vars utilisateur (secrets) sont fusionnées ici, injectées dans
        # le subprocess env UNIQUEMENT — jamais dans devcontainer.json ni dans les logs.
        subprocess_env = {**base_env, **ws_spec.env}

        # Combiner source et branche : "github.com/org/repo@feature-branch"
        devpod_source = ws_spec.source
        if ws_spec.branch:
            devpod_source = f"{ws_spec.source}@{ws_spec.branch}"

        node_ip = self._resolve_node_ip(host_cfg)
        self._write_status(ws_id, "provisioning", login=login)

        task = asyncio.create_task(
            self._run_up_task(
                ws_id, devpod_source, dc_path, subprocess_env, login,
                host_port, node_ip, provider_name=provider_name,
            )
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        _log.info("workspace_up_started", ws_id=ws_id, login=login)
        return ws_id

    async def stop(self, login: str, ws_id: str) -> None:
        """Arrête un workspace en cours d'exécution."""
        if self._exposure is not None:
            try:
                await self._exposure.unexpose(ws_id)
            except Exception as exc:
                _log.warning("workspace_unexpose_failed", ws_id=ws_id, error=type(exc).__name__)
        env = self._minimal_env(login)
        cmd = [*self._devpod_bin, "stop", ws_id]
        log_path = self._log_path(login, f"{ws_id}-stop")
        await run_subprocess(cmd=cmd, env=env, log_path=log_path, ws_id=ws_id)
        self._write_status(ws_id, "stopped", login=login)
        _log.info("workspace_stopped", ws_id=ws_id, login=login)

    async def delete(self, login: str, ws_id: str) -> None:
        """Supprime un workspace (force)."""
        if self._exposure is not None:
            try:
                await self._exposure.unexpose(ws_id)
            except Exception as exc:
                _log.warning("workspace_unexpose_failed", ws_id=ws_id, error=type(exc).__name__)
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
        """Retourne le port hôte alloué depuis le fichier de statut."""
        path = self._status_path(ws_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            p = data.get("host_port")
            return int(p) if p is not None else None
        except (json.JSONDecodeError, ValueError, OSError):
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

    def _write_devcontainer(
        self,
        login: str,
        ws_id: str,
        host_port: int | None = None,
        recipes: list[RecipeMeta] | None = None,
        feature_env: dict[str, str] | None = None,
        extra_sources: list[SourceSpec] | None = None,
    ) -> Path:
        """Écrit devcontainer.json + Feature dirs dans un tmpdir. Retourne le chemin du JSON."""
        user_dir = safe_user_path(login, "devpod")
        user_dir.mkdir(parents=True, exist_ok=True)

        tmp_dir = Path(tempfile.mkdtemp(dir=user_dir, prefix=f"{ws_id}-dc-"))
        try:
            content: dict[str, Any] = {
                "image": "mcr.microsoft.com/devcontainers/base:ubuntu",
            }
            if host_port is not None:
                content["appPorts"] = [f"{host_port}:3000"]

            if recipes:
                features_block: dict[str, dict[str, Any]] = {}
                for recipe in recipes:
                    src = self._recipes_builtin_dir / recipe.id
                    if src.is_dir():
                        shutil.copytree(src, tmp_dir / recipe.id)
                        features_block[f"./{recipe.id}"] = {}
                if features_block:
                    content["features"] = features_block

            if feature_env:
                content["remoteEnv"] = dict(feature_env)

            if extra_sources:
                clone_cmds: list[str] = []
                for src in extra_sources:
                    url = src.url.strip()
                    if not url:
                        continue
                    # Défense en profondeur : rejeter les valeurs commençant par '-'
                    # même si la route les valide déjà (argument injection git).
                    if url.startswith("-"):
                        raise ValueError(f"Source URL must not start with '-': {url!r}")
                    if src.branch and src.branch.startswith("-"):
                        raise ValueError(f"Branch must not start with '-': {src.branch!r}")
                    repo_name = _repo_name_from_url(url)
                    target = f"/workspaces/{repo_name}"
                    # '--' empêche git d'interpréter l'URL comme un flag.
                    if src.branch:
                        clone_cmds.append(
                            f"git clone -b {shlex.quote(src.branch)} -- "
                            f"{shlex.quote(url)} {shlex.quote(target)}"
                        )
                    else:
                        clone_cmds.append(
                            f"git clone -- {shlex.quote(url)} {shlex.quote(target)}"
                        )
                if clone_cmds:
                    content["postCreateCommand"] = " && ".join(clone_cmds)

            dc_path = tmp_dir / "devcontainer.json"
            dc_path.write_text(json.dumps(content, indent=2), encoding="utf-8")
            return dc_path
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    def _resolve_node_ip(self, host_cfg: Any) -> str:
        """Résout l'IP du nœud Docker/SSH depuis l'HostConfig."""
        from ..config.models import HostConfig
        if not isinstance(host_cfg, HostConfig):
            return "127.0.0.1"
        if host_cfg.type == "docker-tls" and host_cfg.docker_host:
            return urlparse(host_cfg.docker_host).hostname or "127.0.0.1"
        if host_cfg.type == "ssh" and host_cfg.address:
            addr = host_cfg.address
            if "@" in addr:
                _, addr = addr.split("@", 1)
            return addr.strip() or "127.0.0.1"
        return "127.0.0.1"

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
        host_port: int | None = None,
        node_ip: str = "127.0.0.1",
        provider_name: str = "",
    ) -> None:
        """Tâche de fond : exécute devpod up, expose le workspace si running."""
        try:
            cmd = [
                *self._devpod_bin,
                "up",
                "--id",
                ws_id,
                "--ide",
                "openvscode",
                "--devcontainer-path",
                str(dc_path),
                "--open-ide=false",  # v0.6.15 : empêche l'ouverture auto du navigateur
            ]
            if provider_name:
                cmd += ["--provider", provider_name]
            if source:
                cmd += [
                    "--",  # fin des flags — défense en profondeur contre l'injection argv
                    source,
                ]
            log_path = self._log_path(login, ws_id)
            # Seul le returncode est logué — la valeur des env vars (secrets) n'est jamais écrite
            returncode = await run_subprocess(cmd=cmd, env=env, log_path=log_path, ws_id=ws_id)
            status = "running" if returncode == 0 else "failed"
            extra: dict[str, Any] = {"returncode": returncode}
            if status == "running" and self._exposure is not None and host_port is not None:
                try:
                    url = await self._exposure.expose(
                        ws_id=ws_id,
                        node_ip=node_ip,
                        host_port=host_port,
                    )
                    extra["url"] = url
                    extra["host_port"] = host_port
                except Exception as exc:
                    _log.error(
                        "workspace_expose_failed",
                        ws_id=ws_id,
                        error=type(exc).__name__,
                    )
            elif host_port is not None:
                extra["host_port"] = host_port
            self._write_status(ws_id, status, login=login, **extra)
            if returncode != 0:
                _log.warning("workspace_up_failed", ws_id=ws_id, returncode=returncode)
            else:
                _log.info("workspace_up_done", ws_id=ws_id, login=login)
        except Exception as exc:
            self._write_status(ws_id, "failed", login=login, error=type(exc).__name__)
            _log.error("workspace_up_crashed", ws_id=ws_id, error=type(exc).__name__)
        finally:
            with contextlib.suppress(Exception):
                shutil.rmtree(dc_path.parent, ignore_errors=True)
