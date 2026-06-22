from __future__ import annotations

import uuid

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db import mcp as db
from .models import BackendCreate

_log = structlog.get_logger(__name__)


class MCPError(Exception):
    pass


class NamespaceTaken(MCPError):
    pass


class NotFound(MCPError):
    pass


class InvalidReference(MCPError):
    pass


def new_id() -> str:
    return uuid.uuid4().hex


async def create_backend(conn: AsyncConnection, owner_login: str, body: BackendCreate) -> str:
    bid = new_id()
    try:
        await db.insert_backend(
            conn,
            id=bid,
            owner_login=owner_login,
            namespace=body.namespace,
            name=body.name,
            url=body.url,
            transport=body.transport,
        )
    except IntegrityError as exc:
        raise NamespaceTaken(f"namespace '{body.namespace}' déjà utilisé") from exc
    _log.info("mcp_backend_created", login=owner_login, namespace=body.namespace)
    return bid
