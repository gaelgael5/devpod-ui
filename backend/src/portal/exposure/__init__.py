from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path

import structlog

from .caddy import CaddyClient
from .ports import PortRegistry

_log = structlog.get_logger(__name__)


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
    ) -> None:
        self._caddy = caddy
        self._registry = registry
        self._data_root = data_root
        self._base_domain = base_domain

    async def allocate_port(self, ws_id: str) -> int:
        """Délègue l'allocation de port au PortRegistry.

        Args:
            ws_id: identifiant du workspace (pour les logs du registre).

        Returns:
            Port hôte unique dans la plage 40000-49999.
        """
        return await self._registry.allocate(ws_id)

    async def expose(self, ws_id: str, node_ip: str, host_port: int) -> str:
        """Crée la route Caddy et persiste les métadonnées d'exposition.

        Args:
            ws_id: identifiant du workspace.
            node_ip: adresse IP du nœud Docker hébergeant le workspace.
            host_port: port hôte alloué (openvscode-server exposé par Docker).

        Returns:
            URL publique HTTPS du workspace.
        """
        route_id = f"ws-{ws_id}"
        match_host = f"{route_id}.{self._base_domain}"
        upstream = f"{node_ip}:{host_port}"
        await self._caddy.upsert_route(
            route_id=route_id,
            match_host=match_host,
            upstream=upstream,
        )
        url = f"https://{match_host}"
        self._write_exposure(ws_id, hostname=match_host, url=url)
        _log.info("workspace_exposed", ws_id=ws_id, url=url)
        return url

    async def unexpose(self, ws_id: str) -> None:
        """Supprime la route Caddy et vide les métadonnées d'exposition.

        Args:
            ws_id: identifiant du workspace à désexposer.
        """
        route_id = f"ws-{ws_id}"
        await self._caddy.remove_route(route_id)
        self._clear_exposure(ws_id)

    # ------------------------------------------------------------------
    # Helpers d'écriture atomique
    # ------------------------------------------------------------------

    def _write_exposure(self, ws_id: str, hostname: str, url: str) -> None:
        """Met à jour (ou crée) routes/<ws_id>.json avec hostname et url.

        Préserve les champs existants (status, login, etc.).
        Écriture atomique : tempfile dans le même répertoire + os.replace.
        """
        path = self._data_root / "routes" / f"{ws_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                data: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {"ws_id": ws_id}
        else:
            data = {"ws_id": ws_id}
        data.update({"hostname": hostname, "url": url})
        self._atomic_write(path, data)

    def _clear_exposure(self, ws_id: str) -> None:
        """Vide hostname et url dans routes/<ws_id>.json.

        No-op si le fichier n'existe pas.
        """
        path = self._data_root / "routes" / f"{ws_id}.json"
        if not path.exists():
            return
        try:
            data: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {"ws_id": ws_id}
        data.update({"hostname": "", "url": ""})
        self._atomic_write(path, data)

    @staticmethod
    def _atomic_write(path: Path, data: dict[str, object]) -> None:
        """Écrit data en JSON de façon atomique via tempfile + os.replace."""
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=f"-{path.stem}.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
