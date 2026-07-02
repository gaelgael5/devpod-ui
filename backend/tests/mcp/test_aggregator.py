from __future__ import annotations

import uuid

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import insert_apikey, insert_backend_key
from portal.db.mcp_catalog import upsert_primitive
from portal.db.mcp_profiles import insert_profile, upsert_profile_entry
from portal.db.tables import mcp_backend, users
from portal.mcp.aggregator import (
    AggregatedPrimitive,
    CallTarget,
    _tools_allow,
    aggregate_primitives,
    make_namespaced_uri,
    resolve_call,
    resolve_resource,
    split_namespaced,
    split_namespaced_uri,
)


def test_split_namespaced_first_separator() -> None:
    assert split_namespaced("rag__search") == ("rag", "search")
    # découpe sur le PREMIER __ ; l'original peut en contenir d'autres
    assert split_namespaced("rag__a__b") == ("rag", "a__b")


def test_split_namespaced_invalid() -> None:
    assert split_namespaced("nosep") is None
    assert split_namespaced("__leading") is None


def test_tools_allow_modes() -> None:
    # None : tous les tools autorisés
    assert _tools_allow(None, "x") is True

    # liste explicite : seuls les noms listés sont autorisés
    assert _tools_allow(["a", "c"], "a") is True
    assert _tools_allow(["a", "c"], "b") is False

    # liste vide : aucun tool autorisé
    assert _tools_allow([], "x") is False


async def _seed(conn: AsyncConnection, *, enabled: bool = True) -> None:
    """user alice + backend b1 (ns=rag) + profil p1 + apikey ak1 liée au profil."""
    await conn.execute(
        insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
    )
    await conn.execute(
        insert(mcp_backend).values(
            id="b1", owner_login="alice", namespace="rag", name="RAG",
            url="https://rag/mcp", transport="streamable_http", enabled=enabled,
        )
    )
    await insert_profile(conn, id="p1", owner_login="alice", name="Profil test")
    await insert_apikey(
        conn, id="ak1", owner_login="alice", token_hash="h", label="", profile_id="p1"
    )


async def _grant_backend(
    conn: AsyncConnection,
    *,
    backend_key_id: str | None = None,
    tools: list[str] | None = None,
) -> None:
    """Entry de profil p1 → b1 (équivalent de l'ancien grant apikey→backend)."""
    await upsert_profile_entry(
        conn, profile_id="p1", backend_id="b1",
        backend_key_id=backend_key_id, tools=tools,
    )


async def test_aggregate_namespaces_and_excludes_quarantined(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await _grant_backend(db_conn)
    await upsert_primitive(
        db_conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "search"}, definition_hash="h1",
    )
    # un tool quarantined doit être exclu
    await upsert_primitive(
        db_conn, backend_id="b1", kind="tool", original_name="evil",
        definition={"name": "evil"}, definition_hash="h2",
    )
    await upsert_primitive(  # redéfinition → quarantaine collante
        db_conn, backend_id="b1", kind="tool", original_name="evil",
        definition={"name": "evil2"}, definition_hash="h2b",
    )

    prims = await aggregate_primitives(
        db_conn, apikey_id="ak1", owner_login="alice", kind="tool"
    )
    names = {p.namespaced_name for p in prims}
    assert names == {"rag__search"}
    assert prims[0] == AggregatedPrimitive(
        namespaced_name="rag__search", kind="tool", backend_id="b1",
        original_name="search", definition={"name": "search"}, namespace="rag",
    )


async def test_aggregate_tools_filter(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    for name in ("a", "b", "c"):
        await upsert_primitive(
            db_conn, backend_id="b1", kind="tool", original_name=name,
            definition={"name": name}, definition_hash=name,
        )

    # tools = subset explicite → seuls les tools listés sont exposés
    await _grant_backend(db_conn, tools=["a", "c"])
    subset = await aggregate_primitives(db_conn, apikey_id="ak1", owner_login="alice", kind="tool")
    assert {p.original_name for p in subset} == {"a", "c"}

    # tools = None → tous les tools du backend
    await _grant_backend(db_conn, tools=None)
    everything = await aggregate_primitives(
        db_conn, apikey_id="ak1", owner_login="alice", kind="tool"
    )
    assert {p.original_name for p in everything} == {"a", "b", "c"}

    # tools = [] → aucun tool
    await _grant_backend(db_conn, tools=[])
    nothing = await aggregate_primitives(db_conn, apikey_id="ak1", owner_login="alice", kind="tool")
    assert nothing == []


async def test_aggregate_apikey_without_profile(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await _grant_backend(db_conn)
    # apikey sans profil → aucune primitive (deny-by-default)
    await insert_apikey(
        db_conn, id="ak2", owner_login="alice", token_hash="h2", label="", profile_id=None
    )
    prims = await aggregate_primitives(db_conn, apikey_id="ak2", owner_login="alice", kind="tool")
    assert prims == []


async def test_aggregate_skips_disabled_backend(db_conn: AsyncConnection) -> None:
    await _seed(db_conn, enabled=False)
    await _grant_backend(db_conn)
    await upsert_primitive(
        db_conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "search"}, definition_hash="h1",
    )
    prims = await aggregate_primitives(db_conn, apikey_id="ak1", owner_login="alice", kind="tool")
    assert prims == []


async def test_resolve_call_disabled_backend_returns_none(db_conn: AsyncConnection) -> None:
    # backend désactivé → résolution refusée même avec entry + catalogue valides
    # (deny-by-default ; remplace l'ancien concept grant.enabled, disparu du modèle profils)
    await _seed(db_conn, enabled=False)
    await _grant_backend(db_conn)
    await upsert_primitive(
        db_conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "search"}, definition_hash="h1",
    )
    assert await resolve_call(
        db_conn, apikey_id="ak1", owner_login="alice",
        namespaced_name="rag__search", kind="tool",
    ) is None


async def test_resolve_call_routes_to_backend(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await insert_backend_key(
        db_conn, id="k1", backend_id="b1", slug="prod", description="",
        storage_type="local", secret_value_local=b"x",
        secret_value_vault_ref=None, vault_identifier=None,
    )
    await _grant_backend(db_conn, backend_key_id="k1")
    await upsert_primitive(
        db_conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "search"}, definition_hash="h1",
    )

    target = await resolve_call(
        db_conn, apikey_id="ak1", owner_login="alice",
        namespaced_name="rag__search", kind="tool",
    )
    assert target == CallTarget(
        backend_id="b1", original_name="search",
        url="https://rag/mcp", transport="streamable_http", backend_key_id="k1",
    )


async def test_resolve_call_falls_back_to_first_backend_key(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await insert_backend_key(
        db_conn, id="k1", backend_id="b1", slug="prod", description="",
        storage_type="local", secret_value_local=b"x",
        secret_value_vault_ref=None, vault_identifier=None,
    )
    # entry sans clé explicite → fallback sur la première clé enabled du backend
    await _grant_backend(db_conn, backend_key_id=None)
    await upsert_primitive(
        db_conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "search"}, definition_hash="h1",
    )
    target = await resolve_call(
        db_conn, apikey_id="ak1", owner_login="alice",
        namespaced_name="rag__search", kind="tool",
    )
    assert target is not None
    assert target.backend_key_id == "k1"


async def test_resolve_call_unknown_or_malformed_returns_none(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await _grant_backend(db_conn)
    await upsert_primitive(
        db_conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "search"}, definition_hash="h1",
    )
    # mauvais namespace, nom non namespacé, tool inexistant → tous None
    assert await resolve_call(
        db_conn, apikey_id="ak1", owner_login="alice",
        namespaced_name="other__search", kind="tool",
    ) is None
    assert await resolve_call(
        db_conn, apikey_id="ak1", owner_login="alice",
        namespaced_name="nosep", kind="tool",
    ) is None
    assert await resolve_call(
        db_conn, apikey_id="ak1", owner_login="alice",
        namespaced_name="rag__ghost", kind="tool",
    ) is None


async def test_resolve_call_tools_filter_denied_returns_none(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    # subset explicite qui n'inclut pas "search" → refus
    await _grant_backend(db_conn, tools=["other"])
    await upsert_primitive(
        db_conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "search"}, definition_hash="h1",
    )
    assert await resolve_call(
        db_conn, apikey_id="ak1", owner_login="alice",
        namespaced_name="rag__search", kind="tool",
    ) is None


async def test_resolve_call_quarantined_returns_none(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await _grant_backend(db_conn)
    await upsert_primitive(
        db_conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "v1"}, definition_hash="h1",
    )
    await upsert_primitive(  # redéfinition → quarantaine collante
        db_conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "v2"}, definition_hash="h1b",
    )
    assert await resolve_call(
        db_conn, apikey_id="ak1", owner_login="alice",
        namespaced_name="rag__search", kind="tool",
    ) is None


async def test_resolve_call_public_backend_has_no_key(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    # aucune clé sortante déclarée sur le backend → backend_key_id None
    await _grant_backend(db_conn)
    await upsert_primitive(
        db_conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "search"}, definition_hash="h1",
    )
    target = await resolve_call(
        db_conn, apikey_id="ak1", owner_login="alice",
        namespaced_name="rag__search", kind="tool",
    )
    assert target == CallTarget(
        backend_id="b1", original_name="search",
        url="https://rag/mcp", transport="streamable_http", backend_key_id=None,
    )


@pytest.mark.parametrize(
    "original",
    ["file:///x/y", "resource://foo", "https://h/p?q=1", "file:///"],
)
def test_namespaced_uri_roundtrip(original: str) -> None:
    ns = "rag"
    namespaced = make_namespaced_uri(ns, original)
    # parseable as AnyUrl (le serveur expose un AnyUrl)
    from pydantic import AnyUrl
    assert str(AnyUrl(namespaced))  # ne lève pas
    parsed = split_namespaced_uri(namespaced)
    assert parsed == (ns, original)


def test_split_namespaced_uri_rejects_foreign() -> None:
    assert split_namespaced_uri("file:///x") is None
    assert split_namespaced_uri("https://h/p") is None
    assert split_namespaced_uri("gw+:///foo") is None


async def test_resolve_resource_routes(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)  # helper : user alice, backend b1 ns=rag enabled, profil p1, apikey ak1
    await _grant_backend(db_conn)
    await upsert_primitive(
        db_conn, backend_id="b1", kind="resource", original_name="resource://foo",
        definition={"uri": "resource://foo", "name": "Foo"}, definition_hash="h1",
    )
    namespaced = make_namespaced_uri("rag", "resource://foo")
    target = await resolve_resource(
        db_conn, apikey_id="ak1", owner_login="alice", namespaced_uri=namespaced
    )
    assert target is not None
    assert target.backend_id == "b1" and target.original_name == "resource://foo"


async def test_resolve_resource_denied(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await _grant_backend(db_conn)
    # pas de resource au catalogue → None
    assert await resolve_resource(
        db_conn, apikey_id="ak1", owner_login="alice",
        namespaced_uri=make_namespaced_uri("rag", "resource://ghost"),
    ) is None
    # URI étrangère (non gw+) → None
    assert await resolve_resource(
        db_conn, apikey_id="ak1", owner_login="alice", namespaced_uri="file:///x"
    ) is None
