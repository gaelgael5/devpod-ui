from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..settings import get_settings

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["static"])


@router.get("/install-node.sh", include_in_schema=False)
async def serve_install_node_script() -> FileResponse:
    """Sert le script d'enrôlement des nœuds (téléchargeable sans auth)."""
    path = Path(get_settings().scripts_dir) / "install-node.sh"
    if not path.is_file():
        _log.error("install_node_script_not_found", path=str(path))
        raise HTTPException(status_code=404, detail="install-node.sh not found")
    return FileResponse(path, media_type="text/plain; charset=utf-8")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
