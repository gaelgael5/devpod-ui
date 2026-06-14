from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
from pathlib import Path
from typing import Any

import structlog
import yaml
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from ..auth.rbac import UserInfo, require_admin
from ..config.store import _data_root

_log = structlog.get_logger(__name__)

router_admin = APIRouter(tags=["recipe-sources"])

_DEFAULT_SOURCE = (
    "https://raw.githubusercontent.com/gaelgael5/devpod-ui/dev/recipes/toc.txt"
)


class RecipeSourcesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[str]


def _sources_path() -> Path:
    return _data_root() / "recipe-sources.yaml"


def _load_sources() -> list[str]:
    path = _sources_path()
    if not path.exists():
        return [_DEFAULT_SOURCE]
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("sources", [_DEFAULT_SOURCE]))


def _save_sources(sources: list[str]) -> None:
    path = _sources_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(yaml.dump({"sources": sources}, default_flow_style=False))
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


@router_admin.get("/recipe-sources")
async def get_recipe_sources(
    user: UserInfo = Depends(require_admin),
) -> dict[str, Any]:
    sources = await asyncio.to_thread(_load_sources)
    return {"sources": sources}


@router_admin.put("/recipe-sources")
async def put_recipe_sources(
    body: RecipeSourcesPayload,
    user: UserInfo = Depends(require_admin),
) -> dict[str, Any]:
    await asyncio.to_thread(_save_sources, body.sources)
    _log.info("recipe_sources_updated", count=len(body.sources), by=user.login)
    return {"sources": body.sources}
