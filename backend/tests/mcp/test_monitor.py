from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import ServerCapabilities
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

import portal.mcp.monitor as monitor_mod
from portal.db.tables import mcp_backend, users
from portal.mcp.connections import BackendUnavailable
from portal.mcp.monitor import (
    BackendHealth,
    get_health,
    health_snapshot,
    monitor_backend_once,
    reset_health,
    run_monitor_pass,
    set_health,
)


def test_get_health_unknown_by_default() -> None:
    reset_health()
    assert get_health("b1") == BackendHealth(status="unknown")


def test_set_and_get_health() -> None:
    reset_health()
    set_health("b1", BackendHealth(status="up"))
    set_health("b2", BackendHealth(status="down", error="boom"))
    assert get_health("b1").status == "up"
    assert get_health("b2") == BackendHealth(status="down", error="boom")


def test_health_snapshot_is_copy() -> None:
    reset_health()
    set_health("b1", BackendHealth(status="up"))
    snap = health_snapshot()
    set_health("b2", BackendHealth(status="up"))
    assert "b2" not in snap  # snapshot pris avant n'est pas muté
    assert snap["b1"].status == "up"


# ---------------------------------------------------------------------------
# monitor_backend_once
# ---------------------------------------------------------------------------


def _fake_backend() -> FastMCP:
    srv = FastMCP("demo")

    @srv.tool()
    def echo(text: str) -> str:
        return text

    return srv


def _patched_open_session(server: FastMCP):
    @asynccontextmanager
    async def _factory(url: str, *, bearer: str | None = None, **kw):
        async with create_connected_server_and_client_session(server) as session:
            yield session

    return _factory


async def _seed_backend(conn: AsyncConnection) -> dict:
    await conn.execute(
        insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
    )
    await conn.execute(insert(mcp_backend).values(
        id="b1", owner_login="alice", namespace="rag", name="RAG",
        url="https://rag/mcp", transport="streamable_http", enabled=True))
    return {"id": "b1", "owner_login": "alice", "namespace": "rag", "name": "RAG",
            "url": "https://rag/mcp", "transport": "streamable_http", "enabled": True}


async def test_monitor_backend_once_up(db_conn: AsyncConnection) -> None:
    reset_health()
    backend = await _seed_backend(db_conn)
    health = await monitor_backend_once(
        db_conn, backend, open_session_fn=_patched_open_session(_fake_backend())
    )
    assert health.status == "up"
    assert get_health("b1").status == "up"
    # le catalogue a été synchronisé
    from portal.db.mcp_catalog import list_primitives
    assert len(await list_primitives(db_conn, "b1", "tool")) == 1


async def test_monitor_backend_once_internal_resyncs_catalog(db_conn: AsyncConnection) -> None:
    """Backend interne (devpod) : toujours 'up', et son catalogue est resynchronisé
    (auparavant un no-op — seul un redémarrage du portail ou un nouveau user le faisait)."""
    reset_health()
    await db_conn.execute(
        insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
    )
    backend = {
        "id": "devpod-alice", "owner_login": "alice", "namespace": "devpod",
        "name": "DevPod workspaces", "url": "", "transport": "internal", "enabled": True,
    }
    await db_conn.execute(insert(mcp_backend).values(**backend))

    health = await monitor_backend_once(db_conn, backend)

    assert health.status == "up"
    from portal.db.mcp_catalog import list_primitives
    assert len(await list_primitives(db_conn, "devpod-alice", "tool")) > 0


async def test_monitor_backend_once_down(db_conn: AsyncConnection) -> None:
    reset_health()
    backend = await _seed_backend(db_conn)

    @asynccontextmanager
    async def _unavailable(url: str, *, bearer: str | None = None, **kw):
        raise BackendUnavailable("down", backend_id="b1")
        yield  # noqa: RET504  # unreachable, fait du factory un générateur

    health = await monitor_backend_once(db_conn, backend, open_session_fn=_unavailable)
    assert health.status == "down" and health.error is not None
    assert get_health("b1").status == "down"


# ---------------------------------------------------------------------------
# run_monitor_pass
# ---------------------------------------------------------------------------


async def _seed_two_backends(engine: AsyncEngine) -> None:
    """Insère deux backends enabled (b1 et b2) pour les tests de passe complète."""
    async with engine.begin() as conn:
        await conn.execute(
            insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
        )
        await conn.execute(
            insert(mcp_backend).values(
                id="b1", owner_login="alice", namespace="rag", name="RAG",
                url="https://rag/mcp", transport="streamable_http", enabled=True,
            )
        )
        await conn.execute(
            insert(mcp_backend).values(
                id="b2", owner_login="alice", namespace="search", name="Search",
                url="https://search/mcp", transport="streamable_http", enabled=True,
            )
        )


async def test_run_monitor_pass_sets_health_for_all_enabled(
    db_engine: AsyncEngine,
) -> None:
    """run_monitor_pass ouvre ses propres connexions via _get_engine().

    b1 répond (up), b2 lève une erreur réseau → la passe continue quand même
    et b1 est up à la fin.
    """
    reset_health()
    await _seed_two_backends(db_engine)

    # On veut b1 → up, b2 → erreur tolérée. On route selon l'URL.
    b1_server = _fake_backend()

    @asynccontextmanager
    async def _routing_session(url: str, *, bearer: str | None = None, **kw):
        if "rag" in url:
            async with create_connected_server_and_client_session(b1_server) as session:
                yield session
        else:
            raise BackendUnavailable("network error", backend_id="b2")

    await run_monitor_pass(open_session_fn=_routing_session)

    assert get_health("b1").status == "up"
    # b2 a levé → down enregistré (monitor_backend_once catch BackendUnavailable)
    assert get_health("b2").status == "down"


async def test_run_monitor_pass_tolerates_non_unavailable_error(
    db_engine: AsyncEngine,
) -> None:
    """Une erreur non-BackendUnavailable (ex. RuntimeError) dans open_session_fn :
    - run_monitor_pass ne propage pas l'exception (la passe se termine normalement),
    - la santé du backend conserve sa dernière valeur connue (pas de faux "down").
    """
    reset_health()
    await _seed_two_backends(db_engine)
    # Pré-positionner b1 à "up" pour vérifier qu'il n'est pas retourné à "unknown"
    set_health("b1", BackendHealth(status="up"))

    @asynccontextmanager
    async def _boom(url: str, *, bearer: str | None = None, **kw):
        raise RuntimeError("boom")
        yield  # noqa: RET504

    # N'implose pas
    await run_monitor_pass(open_session_fn=_boom)

    # La santé de b1 conserve sa dernière valeur ("up"), pas de faux "down"
    assert get_health("b1").status == "up"


# ---------------------------------------------------------------------------
# Bug 026 : aucune connexion DB tenue ouverte pendant l'I/O réseau du probe.
# Tests purement mockés (pas de db_conn/db_engine) : pas besoin de Docker.
# ---------------------------------------------------------------------------


class _FakeConnCM:
    """Async context manager qui journalise entrée/sortie dans `events`."""

    def __init__(self, events: list[str], label: str) -> None:
        self._events = events
        self._label = label

    async def __aenter__(self) -> object:
        self._events.append(f"{self._label}_enter")
        return object()

    async def __aexit__(self, *exc: object) -> None:
        self._events.append(f"{self._label}_exit")


class _FakeEngine:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def connect(self) -> _FakeConnCM:
        return _FakeConnCM(self._events, "connect")

    def begin(self) -> _FakeConnCM:
        return _FakeConnCM(self._events, "begin")


class _FakeSession:
    def get_server_capabilities(self) -> ServerCapabilities:
        # Aucune capability annoncée → fetch_primitives ne fait aucun appel réseau
        # supplémentaire (list_tools/list_resources/list_prompts), suffisant pour
        # vérifier l'ordre des acquisitions de connexion autour du round-trip.
        return ServerCapabilities()


async def test_monitor_backend_once_no_conn_never_holds_db_during_network(
    monkeypatch,
) -> None:
    """conn=None (run_monitor_pass) : la connexion du bearer est relâchée avant le
    round-trip réseau, et la transaction d'écriture n'ouvre qu'après (bug 026)."""
    events: list[str] = []
    engine = _FakeEngine(events)
    monkeypatch.setattr(monitor_mod, "_get_engine", lambda: engine)

    async def fake_resolve_bearer(conn: object, backend_id: str) -> str | None:
        return None

    monkeypatch.setattr(monitor_mod, "_resolve_monitor_bearer", fake_resolve_bearer)

    @asynccontextmanager
    async def fake_open_session(url: str, *, transport: str, bearer: str | None = None):
        events.append("network_enter")
        yield _FakeSession()
        events.append("network_exit")

    reset_health()
    backend = {
        "id": "b1", "owner_login": "alice", "namespace": "rag", "name": "RAG",
        "url": "https://rag/mcp", "transport": "streamable_http", "enabled": True,
    }
    health = await monitor_backend_once(None, backend, open_session_fn=fake_open_session)

    assert health.status == "up"
    assert events == ["connect_enter", "connect_exit", "network_enter", "network_exit",
                       "begin_enter", "begin_exit"]


# ---------------------------------------------------------------------------
# probe_backend_key — test d'une clé de service précise
# ---------------------------------------------------------------------------


class _FakeSecret:
    def reveal(self) -> str:
        return "tok"


_KEY_BACKEND = {"id": "b1", "url": "https://rag/mcp", "transport": "streamable_http"}


_KEY_ROW_DEFAULT = object()


def _patch_key_resolution(
    monkeypatch, *, secret=None, resolve_error=None, key_row=_KEY_ROW_DEFAULT
):
    row = {"id": "k1"} if key_row is _KEY_ROW_DEFAULT else key_row

    async def fake_get_secret(conn, backend_id, key_id):
        return row

    async def fake_resolve(row):
        if resolve_error is not None:
            raise resolve_error
        return secret

    monkeypatch.setattr(monitor_mod, "get_backend_key_secret", fake_get_secret)
    monkeypatch.setattr(monitor_mod, "resolve_grant_key", fake_resolve)


async def test_probe_backend_key_ok(monkeypatch) -> None:
    _patch_key_resolution(monkeypatch, secret=_FakeSecret())
    result = await monitor_mod.probe_backend_key(
        None, _KEY_BACKEND, "k1", open_session_fn=_patched_open_session(_fake_backend())
    )
    assert result.status == "ok"
    assert result.error is None


async def test_probe_backend_key_uses_the_requested_key_bearer(monkeypatch) -> None:
    """Le handshake est fait avec LA clé demandée, pas la première résoluble."""
    _patch_key_resolution(monkeypatch, secret=_FakeSecret())
    seen: list[str | None] = []

    @asynccontextmanager
    async def _spy(url: str, *, bearer: str | None = None, **kw):
        seen.append(bearer)
        async with create_connected_server_and_client_session(_fake_backend()) as session:
            yield session

    await monitor_mod.probe_backend_key(None, _KEY_BACKEND, "k1", open_session_fn=_spy)
    assert seen == ["tok"]


async def test_probe_backend_key_connection_refused(monkeypatch) -> None:
    _patch_key_resolution(monkeypatch, secret=_FakeSecret())

    @asynccontextmanager
    async def _refuse(url: str, *, bearer: str | None = None, **kw):
        raise BackendUnavailable("HTTP 401 Unauthorized")
        yield  # pragma: no cover

    result = await monitor_mod.probe_backend_key(
        None, _KEY_BACKEND, "k1", open_session_fn=_refuse
    )
    assert result.status == "failed"
    assert "401" in (result.error or "")


async def test_probe_backend_key_unresolvable_secret(monkeypatch) -> None:
    _patch_key_resolution(
        monkeypatch, resolve_error=monitor_mod.UnresolvableSecret("vault verrouillé")
    )
    result = await monitor_mod.probe_backend_key(None, _KEY_BACKEND, "k1")
    assert result.status == "failed"
    assert "vault" in (result.error or "")


async def test_probe_backend_key_unknown_key(monkeypatch) -> None:
    _patch_key_resolution(monkeypatch, key_row=None)
    import pytest

    with pytest.raises(KeyError):
        await monitor_mod.probe_backend_key(None, _KEY_BACKEND, "ghost")
