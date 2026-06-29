"""Orchestration : render + persist + delete + sweep."""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from . import db as mdb
from .renderer import render

_log = structlog.get_logger(__name__)


async def render_and_create(
    conn: AsyncConnection,
    *,
    key: str,
    culture: str,
    owner_login: str,
    workspace_name: str,
    msg_type: str,
    ctx: dict[str, Any],
) -> int | None:
    """Résout le template (key, culture) avec fallback 'en', rend, insère.

    Retourne l'id du message créé, ou None si aucun template n'existe.
    Non-bloquant sur erreur de rendu (log + None).
    """
    body = await mdb.get_template_with_fallback(conn, key, culture)
    if body is None:
        _log.debug("jinja2_template_not_found", key=key, culture=culture)
        return None
    try:
        rendered = render(body, ctx)
    except Exception as exc:
        _log.warning("jinja2_render_error", key=key, culture=culture, error=str(exc))
        return None
    return await mdb.create_message(conn, owner_login, workspace_name, msg_type, rendered)


async def delete_message(conn: AsyncConnection, message_id: int | None) -> None:
    """Supprime un message si message_id n'est pas None."""
    if message_id is not None:
        await mdb.delete_message(conn, message_id)


async def sweep_orphans(conn: AsyncConnection) -> None:
    count = await mdb.sweep_orphan_messages(conn)
    if count:
        _log.info("workspace_message_orphans_swept", count=count)
