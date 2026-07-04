from __future__ import annotations

import re
from urllib.parse import urlparse

import structlog

from ..db.engine import _get_engine
from ..db.workspace_status import get_status_db, upsert_status_db
from ..net import build_resolve_fqdn, is_ipv4, resolve_ipv4
from .caddy import CaddyClient
from .ports import PortRegistry

_log = structlog.get_logger(__name__)

# Regex canonique de ws_id — SEULE définition du projet (bug 040 : service.py et
# ce module avaient deux regex différentes ; un ws_id validé par
# DevPodService._ws_id() pouvait être rejeté ici, écrivant un statut "running"
# sans URL ni route Caddy, silencieusement).
#
# login (jusqu'à 40 chars, autorise les points — comptes LDAP) + "-" + name
# (jusqu'à 32 chars, sans point) = jusqu'à 73 caractères bruts. Mais le
# sous-domaine Caddy réel est "ws-{ws_id}" : un label DNS (RFC 1035) est limité à
# 63 caractères, donc ws_id est plafonné à 60 pour laisser la place au préfixe
# "ws-". _ws_id() (devpod/service.py) importe cette même regex : toute
# combinaison login+name qui la passe est garantie acceptée par expose().
_WS_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,58}[a-z0-9]$")


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
        local_domain: str = "",
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
        self._local_domain = local_domain
        self._vs_proxy_domain = vs_proxy_domain
        self._vs_proxy_verify_uri = vs_proxy_verify_uri

    async def _resolved_workspace_host(self) -> str:
        """workspace_host prêt pour une URL navigateur.

        Vide si non configuré. IP littérale → telle quelle. Sinon hostname
        re-résolu en IP courante via `<workspace_host>.<local_domain>` (couvre le
        DHCP) ; en cas d'échec de résolution, on retombe sur le hostname littéral.
        """
        wh = self._workspace_host.strip()
        if not wh or is_ipv4(wh):
            return wh
        fqdn = build_resolve_fqdn(wh, self._local_domain)
        try:
            return await resolve_ipv4(fqdn)
        except OSError as exc:
            _log.warning("workspace_host_resolve_failed", host=wh, fqdn=fqdn, error=str(exc))
            return wh

    async def allocate_port(self, ws_id: str) -> int:
        """Délègue l'allocation de port au PortRegistry.

        Args:
            ws_id: identifiant du workspace (pour les logs du registre).

        Returns:
            Port hôte unique dans la plage 40000-49999.
        """
        return await self._registry.allocate(ws_id)

    async def release_port(self, port: int) -> None:
        """Libère un port alloué mais jamais persisté en DB (échec avant `up()` — bug 037)."""
        await self._registry.release(port)

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
            # Proxy VS Code applicatif : une route Caddy statique rewrite /* → /vsproxy/*
            # et proxy vers le portail Python. L'auth est gérée dans /vsproxy/* (Option A).
            # La route est idempotente : on la (re)crée à chaque expose() pour garantir
            # qu'elle existe même après un restart Caddy.
            if self._caddy is not None:
                portal_upstream = urlparse(self._vs_proxy_verify_uri).netloc
                await self._caddy.upsert_vs_portal_route(
                    match_host=self._vs_proxy_domain,
                    portal_upstream=portal_upstream,
                )
            url = f"{self._url_scheme}://{self._vs_proxy_domain}/?folder={folder}"
            await self._write_exposure(ws_id, hostname=self._vs_proxy_domain, url=url)
            _log.info("workspace_exposed_vs_portal", ws_id=ws_id, url=url)
            return url

        if self._dev_mode:
            host = (
                request_host
                or await self._resolved_workspace_host()
                or urlparse(self._external_url).hostname
                or "localhost"
            )
            url = f"http://{host}:{host_port}/?folder={folder}"
            await self._write_exposure(ws_id, hostname=f"{host}:{host_port}", url=url)
            _log.info("workspace_exposed", ws_id=ws_id, url=url)
            return url

        if not self._base_domain:
            # Pas de base_domain → impossible de router par sous-domaine.
            # Fallback URL directe : priorité au workspace_host configuré (résolu en
            # IP courante si hostname), puis à l'IP routable du nœud Docker, puis
            # l'hôte de la requête.
            host = (
                await self._resolved_workspace_host()
                or (node_ip if is_ipv4(node_ip) else None)
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
