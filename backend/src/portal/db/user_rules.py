"""Couche db des règles utilisateur (moteur sonde → condition → action)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import user_rules

_FIELDS = (
    "name",
    "enabled",
    "event_type",
    "conditions",
    "actions",
    "next_rule_id",
)


async def list_rules(conn: AsyncConnection, owner_login: str) -> list[dict[str, Any]]:
    stmt = (
        select(user_rules)
        .where(user_rules.c.owner_login == owner_login)
        .order_by(user_rules.c.created_at)
    )
    return [dict(r) for r in (await conn.execute(stmt)).mappings().all()]


async def list_enabled_rules_for_event(
    conn: AsyncConnection, owner_login: str, event_type: str
) -> list[dict[str, Any]]:
    stmt = (
        select(user_rules)
        .where(
            user_rules.c.owner_login == owner_login,
            user_rules.c.event_type == event_type,
            user_rules.c.enabled.is_(True),
        )
        .order_by(user_rules.c.created_at)
    )
    return [dict(r) for r in (await conn.execute(stmt)).mappings().all()]


async def get_rule(conn: AsyncConnection, owner_login: str, rule_id: str) -> dict[str, Any] | None:
    stmt = select(user_rules).where(
        user_rules.c.owner_login == owner_login, user_rules.c.id == rule_id
    )
    row = (await conn.execute(stmt)).mappings().first()
    return dict(row) if row else None


async def create_rule(conn: AsyncConnection, *, owner_login: str, **fields: Any) -> str:
    unknown = set(fields) - set(_FIELDS)
    if unknown:
        raise ValueError(f"champs inconnus: {sorted(unknown)}")
    rule_id = str(uuid.uuid4())
    await conn.execute(insert(user_rules).values(id=rule_id, owner_login=owner_login, **fields))
    return rule_id


async def update_rule(conn: AsyncConnection, owner_login: str, rule_id: str, **fields: Any) -> bool:
    unknown = set(fields) - set(_FIELDS)
    if unknown:
        raise ValueError(f"champs inconnus: {sorted(unknown)}")
    stmt = (
        update(user_rules)
        .where(user_rules.c.owner_login == owner_login, user_rules.c.id == rule_id)
        .values(updated_at=func.now(), **fields)
        .returning(user_rules.c.id)
    )
    return (await conn.execute(stmt)).first() is not None


async def delete_rule(conn: AsyncConnection, owner_login: str, rule_id: str) -> bool:
    stmt = (
        delete(user_rules)
        .where(user_rules.c.owner_login == owner_login, user_rules.c.id == rule_id)
        .returning(user_rules.c.id)
    )
    return (await conn.execute(stmt)).first() is not None
