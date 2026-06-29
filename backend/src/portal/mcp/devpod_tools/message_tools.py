"""MCP tools — messages contextuels workspace."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from ...messages import db as mdb

_MESSAGES_TOOL = "workspace_messages"


async def _workspace_messages(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    ws = str(args.get("workspace_name") or "")
    if not ws:
        raise ValueError("workspace_name est requis")
    limit = int(args.get("limit") or 50)
    if not (1 <= limit <= 500):
        raise ValueError("limit doit être entre 1 et 500")
    msgs = await mdb.list_messages(conn, owner_login, ws, limit=limit)
    return [
        {
            "id": m.id,
            "type": m.type,
            "message": m.message,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in msgs
    ]


MESSAGE_IMPLS: dict[str, Any] = {
    _MESSAGES_TOOL: _workspace_messages,
}
