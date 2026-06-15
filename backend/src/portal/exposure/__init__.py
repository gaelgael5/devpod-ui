from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import structlog

from .caddy import CaddyClient
from .ports import PortRegistry

_log = structlog.get_logger(__name__)

# Regex de validation des ws_id : même contrainte que les logins utilisateur.
# Format : alphanumérique, tirets, points, underscores ; 2–40 caractères.
_WS_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,38}[a-z0-9]$")


def _safe_route_path(ws_id: str, data_root: Path) -> Path:
    """Retourne le chemin vers routes/<ws_id>.json après validation du ws_id.

    Lève ValueError si ws_id contient des caractères interdits (path traversal, etc.).
    """
    if not _WS_ID_RE.fullmatch(ws_id):
        raise ValueError(f"Invalid ws_id: {ws_id!r}")
    routes_dir = data_root / "routes"
    path = routes_dir / f"{ws_id}.json"
    if not path.is_relative_to(routes_dir):
        raise ValueError(f"Path escapes routes directory: {path!r}")
    return path


class ExposureService:
    """Orchestre l'exposition d'un workspace : allocation de port + route Caddy.

    Chaque workspace reçoit un sous-domaine dédié :
        ws-{ws_id}.{base_domain}  →  forward_auth + reverse_proxy vers node_ip:host_port

    Les métadonnées (hostname, url) sont persistées dans routes/<ws_id>.json
    via écriture atomique (tempfile + os.replace).
    """

    def __init__(
        self,
        caddy: CaddyClient,
        registry: PortRegistry,
        data_root: Path,
        base_domain: str,
        url_scheme: str = "https",
        dev_mode: bool = False,
        external_url: str = "",
        workspace_host: str = "",
    ) -> None:
        self._caddy = caddy
        self._registry = registry
        self._data_root = data_root
        self._base_domain = base_domain
        self._url_scheme = url_scheme
        self._dev_mode = dev_mode
        self._external_url = external_url
        self._workspace_host = workspace_host

    async def allocate_port(self, ws_id: str) -> int:
        """Délègue l'allocation de port au PortRegistry.

        Args:
            ws_id: identifiant du workspace (pour les logs du registre).

        Returns:
            Port hôte unique dans la plage 40000-49999.
        """
        return await self._registry.allocate(ws_id)

    async def expose(
        self,
        ws_id: str,
        node_ip: str,
        host_port: int,
        request_host: str = "",
        workspace_folder: str = "",
    ) -> str:
        """Crée la route Caddy (prod) ou génère une URL directe (dev) et persiste les métadonnées.

        En mode dev, bypasse Caddy : le tunnel SSH est déjà bindé sur 0.0.0.0:{host_port}
        dans le container portal, exposé à l'hôte via docker-compose ports mapping.
        En prod, crée la route Caddy subdomain-based habituelle.

        Args:
            ws_id: identifiant du workspace.
            node_ip: adresse IP/hostname du nœud (utilisé en prod uniquement).
            host_port: port hôte alloué (40000-49999).

        Returns:
            URL publique du workspace.
        """
        folder = workspace_folder or f"/workspaces/{ws_id}"
        if self._dev_mode:
            host = (
                request_host
                or self._workspace_host
                or urlparse(self._external_url).hostname
                or "localhost"
            )
            url = f"http://{host}:{host_port}/?folder={folder}"
            await asyncio.to_thread(
                self._write_exposure, ws_id, hostname=f"{host}:{host_port}", url=url
            )
            _log.info("workspace_exposed", ws_id=ws_id, url=url)
            return url

        route_id = f"ws-{ws_id}"
        match_host = f"{route_id}.{self._base_domain}"
        upstream = f"{node_ip}:{host_port}"
        await self._caddy.upsert_route(
            route_id=route_id,
            match_host=match_host,
            upstream=upstream,
        )
        url = f"{self._url_scheme}://{match_host}/?folder={folder}"
        await asyncio.to_thread(self._write_exposure, ws_id, hostname=match_host, url=url)
        _log.info("workspace_exposed", ws_id=ws_id, url=url)
        return url

    async def unexpose(self, ws_id: str) -> None:
        """Supprime la route Caddy (prod) et vide les métadonnées d'exposition.

        En mode dev, pas de route Caddy à supprimer.

        Args:
            ws_id: identifiant du workspace à désexposer.
        """
        if not self._dev_mode:
            route_id = f"ws-{ws_id}"
            await self._caddy.remove_route(route_id)
        await asyncio.to_thread(self._clear_exposure, ws_id)
        _log.info("workspace_unexposed", ws_id=ws_id)

    # ------------------------------------------------------------------
    # Helpers d'écriture atomique
    # ------------------------------------------------------------------

    def _read_route(self, ws_id: str) -> dict[str, object]:
        """Lit routes/<ws_id>.json ; retourne un dict vide (avec ws_id) si absent/corrompu."""
        path = self._data_root / "routes" / f"{ws_id}.json"
        if path.exists():
            try:
                parsed = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, OSError):
                pass
        return {"ws_id": ws_id}

    def _write_exposure(self, ws_id: str, hostname: str, url: str) -> None:
        """Met à jour (ou crée) routes/<ws_id>.json avec hostname et url.

        Préserve les champs existants (status, login, etc.).
        Écriture atomique : tempfile dans le même répertoire + os.replace.
        """
        path = _safe_route_path(ws_id, self._data_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self._read_route(ws_id)
        data.update({"hostname": hostname, "url": url})
        self._atomic_write(path, data)

    def _clear_exposure(self, ws_id: str) -> None:
        """Vide hostname et url dans routes/<ws_id>.json.

        No-op si le fichier n'existe pas.
        """
        path = _safe_route_path(ws_id, self._data_root)
        if not path.exists():
            return
        data = self._read_route(ws_id)
        data.update({"hostname": "", "url": ""})
        self._atomic_write(path, data)

    @staticmethod
    def _atomic_write(path: Path, data: dict[str, object]) -> None:
        """Écrit data en JSON de façon atomique via tempfile + os.replace."""
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=f"-{path.stem}.tmp")
        fd_open = False
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                fd_open = True
                json.dump(data, f)
            os.replace(tmp, path)
        except Exception:
            if not fd_open:
                with contextlib.suppress(OSError):
                    os.close(fd)
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
