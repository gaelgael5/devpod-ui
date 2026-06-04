from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog

_log = structlog.get_logger(__name__)

_PORT_MIN = 40000
_PORT_MAX = 49999


class PortRegistry:
    """Registre d'allocation de ports hôte depuis les fichiers routes/*.json.

    Utilise un verrou asyncio par instance pour garantir l'unicité même en cas
    d'appels concurrents dans la même boucle d'événements. Les ports alloués
    mais pas encore persistés sur disque sont suivis en mémoire (_reserved)
    pour éviter toute collision entre deux appels concurrents.
    """

    def __init__(self, data_root: Path) -> None:
        self._data_root = data_root
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
            disk_ports = await asyncio.to_thread(self._used_ports)
            # Les ports confirmés sur disque sortent de _reserved (déjà persistés)
            self._reserved -= disk_ports
            used = disk_ports | self._reserved
            for port in range(_PORT_MIN, _PORT_MAX + 1):
                if port not in used:
                    self._reserved.add(port)
                    _log.debug("port_allocated", ws_id=ws_id, port=port)
                    return port
            _log.error("port_pool_exhausted", ws_id=ws_id)
            raise RuntimeError("No free port in 40000-49999")

    def _used_ports(self) -> set[int]:
        """Lit tous les routes/*.json et collecte les host_port déjà alloués."""
        routes_dir = self._data_root / "routes"
        used: set[int] = set()
        if not routes_dir.exists():
            return used
        for f in routes_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(p := data.get("host_port"), int):
                    used.add(p)
            except (json.JSONDecodeError, OSError):
                _log.warning("port_json_corrupt", path=str(f))
        return used
