from __future__ import annotations

import asyncio

import structlog

_log = structlog.get_logger(__name__)

# Plage openvscode (host_port) — défaut historique.
_PORT_MIN = 40000
_PORT_MAX = 49999
# Plage SSH par workspace (spec 18 T1), distincte pour pare-feu/lisibilité.
SSH_PORT_MIN = 50000
SSH_PORT_MAX = 59999


class PortRegistry:
    """Registre d'allocation de ports hôte depuis la table workspace_status.

    Paramétrable par plage et par colonne source (`host_port` par défaut pour
    openvscode ; `ssh_port` pour l'accès SSH par workspace) → deux registres
    indépendants sans collision, chacun ne voit que sa colonne.

    Verrou asyncio par instance pour l'unicité sous concurrence. Les ports
    alloués mais pas encore persistés en DB sont suivis en mémoire (_reserved).
    """

    def __init__(
        self,
        port_min: int = _PORT_MIN,
        port_max: int = _PORT_MAX,
        column: str = "host_port",
    ) -> None:
        self._lock = asyncio.Lock()
        self._reserved: set[int] = set()
        self._min = port_min
        self._max = port_max
        self._column = column

    async def allocate(self, ws_id: str) -> int:
        """Alloue le premier port libre dans la plage configurée.

        Args:
            ws_id: identifiant du workspace — utilisé dans les logs.

        Returns:
            Port libre dans la plage configurée.

        Raises:
            RuntimeError: si aucun port n'est disponible dans la plage.
        """
        async with self._lock:
            db_ports = await self._used_ports()
            self._reserved -= db_ports
            used = db_ports | self._reserved
            for port in range(self._min, self._max + 1):
                if port not in used:
                    self._reserved.add(port)
                    _log.debug("port_allocated", ws_id=ws_id, port=port, column=self._column)
                    return port
            _log.error("port_pool_exhausted", ws_id=ws_id, column=self._column)
            raise RuntimeError(f"No free port in {self._min}-{self._max}")

    async def release(self, port: int) -> None:
        """Libère un port réservé en mémoire mais jamais persisté en DB.

        À appeler quand un `up()` échoue après allocate() sans jamais atteindre
        l'écriture DB du host_port (chemin d'exception synchrone dans up(), ou
        crash dans _run_up_task) — sinon le port reste réservé jusqu'au restart
        du portail (bug 037).
        """
        async with self._lock:
            self._reserved.discard(port)

    async def _used_ports(self) -> set[int]:
        """Lit les ports déjà alloués (colonne configurée) de workspace_status."""
        from sqlalchemy import select

        from ..db.engine import _get_engine
        from ..db.tables import workspace_status

        col = workspace_status.c[self._column]
        async with _get_engine().connect() as conn:
            rows = (await conn.execute(select(col))).scalars().all()
        return {int(p) for p in rows if p is not None}
