from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

import structlog

from ..db.engine import _get_engine
from ..db.workspace_status import get_status_db, upsert_status_db
from .caddy import CaddyClient
from .ports import PortRegistry

_log = structlog.get_logger(__name__)

# Regex de validation des ws_id (défense en profondeur, les ws_id sont générés en interne).
_WS_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,38}[a-z0-9]$")


class ExposureService:
    """Orchestre l'exposition d'un workspace : allocation de port + route Caddy.

    Chaque workspace reçoit un sous-domaine dédié :
        ws-{ws_id}.{base_domain}  →  forward_auth + reverse_proxy vers node_ip:host_port

    Les métadonnées (hostname, url) sont persistées dans routes/<ws_id>.json
    via écriture atomique (tempfile + os.replace).
    """

    def __init__(
        self,
        registry: PortRegistry,
        base_domain: str,
        caddy: CaddyClient | None = None,
        url_scheme: str = "https",
        dev_mode: bool = False,
        external_url: str = "",
        workspace_host: str = "",
        vs_proxy_domain: str = "",
        vs_proxy_verify_uri: str = "",
    ) -> None:
        self._caddy = caddy
        self._registry = registry
        self._base_domain = base_domain
        self._url_scheme = url_scheme
        self._dev_mode = dev_mode
        self._external_url = external_url
        self._workspace_host = workspace_host
        self._vs_proxy_domain = vs_proxy_domain
        self._vs_proxy_verify_uri = vs_proxy_verify_uri

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
        if not _WS_ID_RE.fullmatch(ws_id):
            raise ValueError(f"Invalid ws_id: {ws_id!r}")
        folder = workspace_folder or f"/workspaces/{ws_id}"

        if self._vs_proxy_domain:
            # Proxy VS Code à sous-domaine fixe : une seule route Caddy partagée,
            # l'upstream est résolu dynamiquement via /auth/caddy/verify-workspace.
            if self._caddy is not None:
                await self._caddy.upsert_vs_proxy_route(
                    match_host=self._vs_proxy_domain,
                    verify_uri=self._vs_proxy_verify_uri,
                )
            url = f"{self._url_scheme}://{self._vs_proxy_domain}/?folder={folder}"
            await self._write_exposure(ws_id, hostname=self._vs_proxy_domain, url=url)
            _log.info("workspace_exposed_vs_proxy", ws_id=ws_id, url=url)
            return url

        if self._dev_mode:
            host = (
                request_host
                or self._workspace_host
                or urlparse(self._external_url).hostname
                or "localhost"
            )
            url = f"http://{host}:{host_port}/?folder={folder}"
            await self._write_exposure(ws_id, hostname=f"{host}:{host_port}", url=url)
            _log.info("workspace_exposed", ws_id=ws_id, url=url)
            return url

        if not self._base_domain:
            # Pas de base_domain → impossible de router par sous-domaine.
            # Fallback URL directe : priorité à l'IP routable du nœud Docker,
            # puis workspace_host configuré, puis l'hôte de la requête.
            def _is_ip(s: str) -> bool:
                try:
                    ipaddress.ip_address(s)
                    return True
                except ValueError:
                    return False

            host = (
                self._workspace_host
                or (node_ip if _is_ip(node_ip) else None)
                or request_host
                or urlparse(self._external_url).hostname
                or "localhost"
            )
            url = f"http://{host}:{host_port}/?folder={folder}"
            await self._write_exposure(ws_id, hostname=f"{host}:{host_port}", url=url)
            _log.warning(
                "workspace_exposed_no_domain_fallback",
                ws_id=ws_id,
                url=url,
                hint="Configurez server.base_domain pour le routing Caddy",
            )
            return url

        route_id = f"ws-{ws_id}"
        match_host = f"{route_id}.{self._base_domain}"
        upstream = f"{node_ip}:{host_port}"
        if self._caddy is not None:
            await self._caddy.upsert_route(
                route_id=route_id,
                match_host=match_host,
                upstream=upstream,
            )
        url = f"{self._url_scheme}://{match_host}/?folder={folder}"
        await self._write_exposure(ws_id, hostname=match_host, url=url)
        _log.info("workspace_exposed", ws_id=ws_id, url=url)
        return url

    async def unexpose(self, ws_id: str) -> None:
        """Supprime la route Caddy (prod) et vide les métadonnées d'exposition.

        En mode dev, pas de route Caddy à supprimer.

        Args:
            ws_id: identifiant du workspace à désexposer.
        """
        # En mode vs_proxy ou dev_mode, pas de route per-workspace à supprimer.
        if not self._vs_proxy_domain and not self._dev_mode and self._caddy is not None:
            route_id = f"ws-{ws_id}"
            await self._caddy.remove_route(route_id)
        await self._clear_exposure(ws_id)
        _log.info("workspace_unexposed", ws_id=ws_id)

    # ------------------------------------------------------------------
    # Helpers DB
    # ------------------------------------------------------------------

    async def _write_exposure(self, ws_id: str, hostname: str, url: str) -> None:
        """Met à jour workspace_status avec hostname et url (préserve les autres champs)."""
        async with _get_engine().begin() as conn:
            existing = await get_status_db(ws_id, conn)
            if existing is not None:
                await upsert_status_db(
                    ws_id,
                    existing["status"],
                    conn,
                    login=existing.get("login", ""),
                    hostname=hostname,
                    url=url,
                    host_port=existing.get("host_port"),
                    host_type=existing.get("host_type"),
                    host_name=existing.get("host_name"),
                )
            else:
                await upsert_status_db(ws_id, "running", conn, hostname=hostname, url=url)

    async def _clear_exposure(self, ws_id: str) -> None:
        """Vide hostname et url dans workspace_status. No-op si absent."""
        async with _get_engine().begin() as conn:
            existing = await get_status_db(ws_id, conn)
            if existing is None:
                return
            await upsert_status_db(
                ws_id,
                existing["status"],
                conn,
                login=existing.get("login", ""),
                hostname=None,
                url=None,
                host_port=existing.get("host_port"),
                host_type=existing.get("host_type"),
                host_name=existing.get("host_name"),
            )
