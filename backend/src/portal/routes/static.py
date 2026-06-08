from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse

from ..settings import get_settings

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["static"])

_STATIC_DIR = Path("static")


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


@router.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str) -> Response:
    """SPA fallback : sert le fichier statique s'il existe, sinon index.html."""
    if not _STATIC_DIR.is_dir():
        _log.info("spa_static_dir_absent", path=str(_STATIC_DIR))
        raise HTTPException(status_code=404, detail="Frontend not built")

    # Protection traversal — résolution dans le répertoire statique uniquement
    target = (_STATIC_DIR / full_path).resolve()
    if not target.is_relative_to(_STATIC_DIR.resolve()):
        raise HTTPException(status_code=400, detail="Invalid path")

    if target.is_file():
        return FileResponse(target)

    index = _STATIC_DIR / "index.html"
    if index.is_file():
        return FileResponse(index)

    raise HTTPException(status_code=404, detail="Not found")
