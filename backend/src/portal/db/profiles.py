"""Persistance profiles VSCode (table profiles) — remplace ProfileRepository filesystem."""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from ..profiles.models import Profile, ProfileBody, ProfileSummary, Scope
from ..profiles.repository import ProfileError, slugify
from .engine import _get_engine
from .tables import profiles


def _login_key(login: str | None) -> str:
    return login or ""


async def list_profiles_db(
    login: str, is_admin: bool, conn: AsyncConnection
) -> list[ProfileSummary]:
    rows = (
        await conn.execute(
            select(profiles).where(
                (profiles.c.scope == "shared")
                | ((profiles.c.scope == "user") & (profiles.c.login == login))
            )
        )
    ).mappings().all()

    out: list[ProfileSummary] = []
    for r in rows:
        editable = is_admin if r["scope"] == "shared" else True
        out.append(
            ProfileSummary(
                slug=r["slug"],
                scope=r["scope"],
                name=r["name"],
                description=r["description"],
                extension_count=len(r["extensions"] or []),
                editable=editable,
                gallery_source=r.get("gallery_source"),
            )
        )
    return out


async def get_profile_db(
    scope: Scope, slug: str, login: str, conn: AsyncConnection
) -> Profile:
    row = (
        await conn.execute(
            select(profiles).where(
                (profiles.c.slug == slug)
                & (profiles.c.scope == scope)
                & (profiles.c.login_key == _login_key(login if scope == "user" else None))
            )
        )
    ).mappings().one_or_none()
    if row is None:
        raise ProfileError("not_found")
    return _row_to_profile(dict(row))


async def _unique_slug_db(
    base_slug: str, scope: Scope, login: str | None, conn: AsyncConnection
) -> str:
    lk = _login_key(login)
    existing = (
        await conn.execute(
            select(profiles.c.slug).where(
                (profiles.c.scope == scope) & (profiles.c.login_key == lk)
            )
        )
    ).scalars().all()
    slug_set = set(existing)
    if base_slug not in slug_set:
        return base_slug
    i = 2
    while f"{base_slug}-{i}" in slug_set:
        i += 1
    return f"{base_slug}-{i}"


async def _write_profile_db(
    scope: Scope,
    login: str | None,
    slug: str,
    body: ProfileBody,
    allow_overwrite: bool,
    conn: AsyncConnection,
) -> Profile:
    lk = _login_key(login)

    if allow_overwrite:
        final_slug = slug
    else:
        final_slug = await _unique_slug_db(slug, scope, login, conn)

    existing = (
        await conn.execute(
            select(profiles.c.slug).where(
                (profiles.c.slug == final_slug)
                & (profiles.c.scope == scope)
                & (profiles.c.login_key == lk)
            )
        )
    ).scalar_one_or_none()

    vals: dict[str, Any] = {
        "slug": final_slug,
        "scope": scope,
        "login_key": lk,
        "login": login,
        "name": body.name,
        "description": body.description,
        "extensions": list(body.extensions),
        "settings": dict(body.settings),
    }
    if existing is None:
        await conn.execute(insert(profiles).values(**vals))
    else:
        await conn.execute(
            update(profiles)
            .where(
                (profiles.c.slug == final_slug)
                & (profiles.c.scope == scope)
                & (profiles.c.login_key == lk)
            )
            .values(**{k: v for k, v in vals.items() if k not in ("slug", "scope", "login_key")},
                    updated_at=func.now())
        )
    return Profile(slug=final_slug, scope=scope, **body.model_dump())


async def set_gallery_source_db(slug: str, source_url: str, conn: AsyncConnection) -> None:
    await conn.execute(
        update(profiles)
        .where(
            (profiles.c.slug == slug)
            & (profiles.c.scope == "shared")
            & (profiles.c.login_key == "")
        )
        .values(gallery_source=source_url)
    )


def _row_to_profile(row: dict[str, Any]) -> Profile:
    return Profile(
        slug=row["slug"],
        scope=row["scope"],
        name=row["name"],
        description=row["description"],
        extensions=list(row["extensions"] or []),
        settings=dict(row["settings"] or {}),
    )


class AsyncProfileRepository:
    """Repository profiles async s'appuyant sur la DB."""

    async def list(self, login: str, is_admin: bool) -> list[ProfileSummary]:
        async with _get_engine().connect() as conn:
            return await list_profiles_db(login, is_admin, conn)

    async def get(self, scope: Scope, slug: str, login: str) -> Profile:
        async with _get_engine().connect() as conn:
            return await get_profile_db(scope, slug, login, conn)

    async def create(self, login: str, body: ProfileBody) -> Profile:
        async with _get_engine().begin() as conn:
            return await _write_profile_db("user", login, slugify(body.name), body, False, conn)

    async def update(self, login: str, slug: str, body: ProfileBody) -> Profile:
        async with _get_engine().begin() as conn:
            existing = (
                await conn.execute(
                    select(profiles.c.slug).where(
                        (profiles.c.slug == slug)
                        & (profiles.c.scope == "user")
                        & (profiles.c.login_key == login)
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                raise ProfileError("not_found")
            return await _write_profile_db("user", login, slug, body, True, conn)

    async def delete(self, login: str, slug: str) -> None:
        async with _get_engine().begin() as conn:
            result = await conn.execute(
                delete(profiles).where(
                    (profiles.c.slug == slug)
                    & (profiles.c.scope == "user")
                    & (profiles.c.login_key == login)
                )
            )
            if result.rowcount == 0:
                raise ProfileError("not_found")

    async def fork(self, login: str, shared_slug: str) -> Profile:
        async with _get_engine().begin() as conn:
            src = await get_profile_db("shared", shared_slug, login, conn)
            fields = {"name", "description", "extensions", "settings"}
            body = ProfileBody(**src.model_dump(include=fields))
            return await _write_profile_db("user", login, slugify(src.name), body, False, conn)

    async def create_shared(self, body: ProfileBody) -> Profile:
        async with _get_engine().begin() as conn:
            return await _write_profile_db("shared", None, slugify(body.name), body, False, conn)

    async def update_shared(self, slug: str, body: ProfileBody) -> Profile:
        async with _get_engine().begin() as conn:
            existing = (
                await conn.execute(
                    select(profiles.c.slug).where(
                        (profiles.c.slug == slug)
                        & (profiles.c.scope == "shared")
                        & (profiles.c.login_key == "")
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                raise ProfileError("not_found")
            return await _write_profile_db("shared", None, slug, body, True, conn)

    async def delete_shared(self, slug: str) -> None:
        async with _get_engine().begin() as conn:
            result = await conn.execute(
                delete(profiles).where(
                    (profiles.c.slug == slug)
                    & (profiles.c.scope == "shared")
                    & (profiles.c.login_key == "")
                )
            )
            if result.rowcount == 0:
                raise ProfileError("not_found")

    async def set_gallery_source(self, slug: str, source_url: str) -> None:
        async with _get_engine().begin() as conn:
            await set_gallery_source_db(slug, source_url, conn)
