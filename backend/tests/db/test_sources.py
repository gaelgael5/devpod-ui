"""Tests de la couche persistance recipe_sources / profile_sources (Tour 2)."""
from __future__ import annotations

import pytest

from portal.db.sources import (
    _DEFAULT_JINJA_SOURCE,
    _DEFAULT_PROFILE_SOURCE,
    _DEFAULT_RECIPE_SOURCE,
    load_jinja_template_sources,
    load_profile_sources,
    load_recipe_sources,
    save_jinja_template_sources,
    save_profile_sources,
    save_recipe_sources,
)

URL_A = "https://example.com/recipes/toc.txt"
URL_B = "https://example.org/recipes/toc.txt"
PROFILE_URL = "https://example.com/profiles/"


# ─── recipe_sources ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recipe_sources_empty_returns_default(db_conn):
    result = await load_recipe_sources(db_conn)
    assert result == [_DEFAULT_RECIPE_SOURCE]


@pytest.mark.asyncio
async def test_recipe_sources_save_and_load(db_conn):
    await save_recipe_sources([URL_A, URL_B], db_conn)
    result = await load_recipe_sources(db_conn)
    assert result == [URL_A, URL_B]


@pytest.mark.asyncio
async def test_recipe_sources_order_preserved(db_conn):
    await save_recipe_sources([URL_B, URL_A], db_conn)
    result = await load_recipe_sources(db_conn)
    assert result == [URL_B, URL_A]


@pytest.mark.asyncio
async def test_recipe_sources_replace_on_save(db_conn):
    await save_recipe_sources([URL_A, URL_B], db_conn)
    await save_recipe_sources([URL_B], db_conn)
    result = await load_recipe_sources(db_conn)
    assert result == [URL_B]


@pytest.mark.asyncio
async def test_recipe_sources_save_empty_returns_default(db_conn):
    await save_recipe_sources([URL_A], db_conn)
    await save_recipe_sources([], db_conn)
    result = await load_recipe_sources(db_conn)
    assert result == [_DEFAULT_RECIPE_SOURCE]


# ─── profile_sources ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_profile_sources_empty_returns_default(db_conn):
    result = await load_profile_sources(db_conn)
    assert result == [_DEFAULT_PROFILE_SOURCE]


@pytest.mark.asyncio
async def test_profile_sources_save_and_load(db_conn):
    await save_profile_sources([PROFILE_URL], db_conn)
    result = await load_profile_sources(db_conn)
    assert result == [PROFILE_URL]


@pytest.mark.asyncio
async def test_profile_sources_replace_on_save(db_conn):
    await save_profile_sources([PROFILE_URL], db_conn)
    await save_profile_sources([], db_conn)
    result = await load_profile_sources(db_conn)
    assert result == [_DEFAULT_PROFILE_SOURCE]


# ─── jinja_template_sources ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_jinja_sources_default_when_empty(db_conn):
    result = await load_jinja_template_sources(db_conn)
    assert result == [_DEFAULT_JINJA_SOURCE]


@pytest.mark.asyncio
async def test_jinja_sources_save_and_load(db_conn):
    urls = ["https://example.com/jinja/toc.txt", "https://example.org/j/"]
    await save_jinja_template_sources(urls, db_conn)
    result = await load_jinja_template_sources(db_conn)
    assert result == urls
