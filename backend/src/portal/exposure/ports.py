from __future__ import annotations

import asyncio

import structlog

_log = structlog.get_logger(__name__)

_PORT_MIN = 40000
_PORT_MAX = 49999


class PortRegistry:
    """Registre d'allocation de ports hôte depuis la table workspace_status.

    Utilise un verrou asyncio par instance pour garantir l'unicité même en cas
    d'appels concurrents dans la même boucle d'événements. Les ports alloués
    mais pas encore persistés en DB sont suivis en mémoire (_reserved)
    pour éviter toute collision entre deux appels concurrents.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._reserved: set[int] = set()

    async def allocate(self, ws_id: str) -> int:
        """Alloue le premier port libre dans [40000, 49999].

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
            for port in range(_PORT_MIN, _PORT_MAX + 1):
                if port not in used:
                    self._reserved.add(port)
                    _log.debug("port_allocated", ws_id=ws_id, port=port)
                    return port
            _log.error("port_pool_exhausted", ws_id=ws_id)
            raise RuntimeError("No free port in 40000-49999")

    async def _used_ports(self) -> set[int]:
        """Lit les host_port déjà alloués depuis la table workspace_status."""
        from sqlalchemy import select

        from ..db.engine import _get_engine
        from ..db.tables import workspace_status

        async with _get_engine().connect() as conn:
            rows = (
                await conn.execute(select(workspace_status.c.host_port))
            ).scalars().all()
        return {int(p) for p in rows if p is not None}
