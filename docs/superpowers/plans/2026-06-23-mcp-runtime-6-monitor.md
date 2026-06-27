# MCP Runtime — Plan 6 : Monitor (refresh catalogue TTL + health) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Une tâche de fond périodique qui, par backend MCP activé, ré-synchronise le catalogue (`sync_backend`) et en déduit un statut de santé en mémoire (`up`/`down`), exposé dans le tool natif `gateway__list_backends`.

**Architecture:** Modèle **stateless conservé** (pas de pool de sessions longues). Un nouveau module `portal/mcp/monitor.py` tient un registre de santé en mémoire (`dict[backend_id, BackendHealth]`) et la logique d'une passe de monitoring : pour chaque backend `enabled` (tous owners), résoudre une clé (best-effort), ouvrir une session courte (`open_session`), `sync_backend` → `up`, ou `BackendUnavailable` → `down`. Une boucle `monitor_loop` (lancée via `asyncio.create_task` dans le lifespan FastAPI, annulée au shutdown) répète la passe toutes les N secondes (réglable via settings). Le tool natif `gateway__list_backends` lit le registre.

**Hors périmètre (décisions actées) :** notifications `list_changed` push serveur→client (HORS D'ATTEINTE en SDK 1.28 — voir LESSONS `[mcp/server] push serveur→client`) ; réception des notifications backend→gateway (exige des sessions longues / `BackendSessionManager`, sous-projet différé). L'alternative au push = polling court côté frontend (Plan 7).

**Tech Stack:** Python 3.12, asyncio (`create_task`/`sleep`/`cancel`), SQLAlchemy Core async, pydantic v2, SDK `mcp` 1.28 (`sync_backend`, `open_session`), pytest + testcontainers (DB skip local → CI Docker) + faux backend in-memory.

## Global Constraints

- `from __future__ import annotations` ; async partout ; aucune I/O bloquante.
- pydantic v2 `extra="forbid"` ; `BackendHealth` frozen.
- Registre de santé = état module-level en mémoire (cohérent avec `portal.db.engine._engine`) ; fonction `reset_health()` pour l'isolation des tests.
- `open_session` résolu au **call-time** (défaut `None` → global), pour rester monkeypatchable (leçon Plan 5).
- Le monitor n'écrit JAMAIS de secret en log/DB ; le bearer résolu ne sert qu'à `open_session`.
- Chaque sync backend dans sa propre transaction (`_get_engine().begin()`) ; une erreur sur un backend n'interrompt pas la passe (try/except par backend, loggé).
- La boucle de fond est annulée proprement au shutdown (`task.cancel()` + `suppress(CancelledError)` dans le `finally` du lifespan).
- Fichiers ≤ 300 lignes ; logs structlog ; branche `dev` ; commits FR conventionnels ; TDD.
- Tests DB skip local → CI Docker ; sortie pristine (`filterwarnings=error::DeprecationWarning`).

---

## Surface existante consommée

- `portal.mcp.catalog.sync_backend(conn, *, backend_id, session) -> dict` (Plan 2) — sync upsert/prune.
- `portal.mcp.connections.open_session(url, *, bearer=None, ...)` (`@asynccontextmanager`) / `BackendUnavailable`.
- `portal.db.mcp.list_backend_keys(conn, backend_id) -> list[dict]` (colonnes incl. `id, storage_type, enabled`, SANS blob) ; `get_backend_key_secret(conn, backend_id, key_id) -> dict | None` ; `list_backends(conn, owner_login)`.
- `portal.mcp.runtime_secrets.resolve_grant_key(key_row) -> Secret | None` / `UnresolvableSecret` ; `Secret.reveal()`.
- `portal.db.engine._get_engine()` ; pattern `async with _get_engine().begin()/.connect() as conn`.
- `portal.mcp.handlers._gateway_list_backends(conn, owner_login) -> types.CallToolResult` (à enrichir).
- `portal.settings.AppSettings(BaseSettings)` (`backend/src/portal/settings.py`) — ajouter un champ d'intervalle. Accès settings : suivre le pattern existant dans `app.py`.
- Faux backend test : `mcp.server.fastmcp.FastMCP` + `mcp.shared.memory.create_connected_server_and_client_session`.
- Fixture `db_conn` ; seeding `insert(users)`, `insert(mcp_backend)`, `insert_backend_key`.

---

### Task 1 : `monitor.py` — modèle santé + registre mémoire

**Files:**
- Create: `backend/src/portal/mcp/monitor.py`
- Test: `backend/tests/mcp/test_monitor.py`

**Interfaces:**
- Produces:
  - `class BackendHealth(BaseModel, frozen, extra=forbid)` : `status: Literal["up", "down", "unknown"]`, `error: str | None = None`.
  - `set_health(backend_id: str, health: BackendHealth) -> None`
  - `get_health(backend_id: str) -> BackendHealth` — renvoie `BackendHealth(status="unknown")` si absent.
  - `reset_health() -> None` — vide le registre (tests).
  - `health_snapshot() -> dict[str, BackendHealth]` — copie du registre.

- [ ] **Step 1: Test rouge (pur, pas de DB)**

Créer `backend/tests/mcp/test_monitor.py` :

```python
from __future__ import annotations

from portal.mcp.monitor import (
    BackendHealth,
    get_health,
    health_snapshot,
    reset_health,
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
```

- [ ] **Step 2: Lancer (rouge — import)**

Run: `cd /d/srcs/devpod-ui/backend && uv run pytest tests/mcp/test_monitor.py -v`
Expected : échec d'import (`cannot import name 'BackendHealth'`).

- [ ] **Step 3: Implémenter**

Créer `backend/src/portal/mcp/monitor.py` :

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class BackendHealth(BaseModel):
    """Statut de santé d'un backend MCP, dérivé du dernier monitoring."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["up", "down", "unknown"]
    error: str | None = None


_HEALTH: dict[str, BackendHealth] = {}


def set_health(backend_id: str, health: BackendHealth) -> None:
    _HEALTH[backend_id] = health


def get_health(backend_id: str) -> BackendHealth:
    return _HEALTH.get(backend_id, BackendHealth(status="unknown"))


def health_snapshot() -> dict[str, BackendHealth]:
    return dict(_HEALTH)


def reset_health() -> None:
    _HEALTH.clear()
```

- [ ] **Step 4: Vert + lint**

Run: `cd /d/srcs/devpod-ui/backend && uv run pytest tests/mcp/test_monitor.py -v` → 3 PASSED (purs).
Run: `cd /d/srcs/devpod-ui/backend && uv run ruff check src/portal/mcp/monitor.py tests/mcp/test_monitor.py && uv run mypy src/portal/mcp/monitor.py` → propre.

- [ ] **Step 5: Commit**

```bash
cd /d/srcs/devpod-ui && git add backend/src/portal/mcp/monitor.py backend/tests/mcp/test_monitor.py
git commit -m "feat(mcp): monitor — modèle BackendHealth + registre santé en mémoire"
```

---

### Task 2 : `list_all_enabled_backends` + `monitor_backend_once` (sync → santé)

**Files:**
- Modify: `backend/src/portal/db/mcp.py` (ajout `list_all_enabled_backends`)
- Modify: `backend/src/portal/mcp/monitor.py`
- Test: `backend/tests/mcp/test_monitor.py` ; `backend/tests/db/test_mcp.py`

**Interfaces:**
- Produces:
  - `db.mcp.list_all_enabled_backends(conn) -> list[dict]` — TOUS les backends `enabled` (tous owners) ; colonnes `id, owner_login, namespace, name, url, transport, enabled`.
  - `monitor._resolve_monitor_bearer(conn, backend_id) -> str | None` — première clé enabled dont le secret se résout au runtime (KEK/env), sinon `None` (best-effort ; public → `None`).
  - `monitor.monitor_backend_once(conn, backend_row, *, open_session_fn=None) -> BackendHealth` — résout la clé, ouvre la session (call-time `open_session`), `sync_backend` → `up`, `BackendUnavailable` → `down`, écrit le registre via `set_health`, retourne le health.

- [ ] **Step 1: Test rouge**

Ajouter à `backend/tests/db/test_mcp.py` :

```python
from portal.db.mcp import list_all_enabled_backends


async def test_list_all_enabled_backends(db_conn: AsyncConnection) -> None:
    await db_conn.execute(insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4())))
    await db_conn.execute(insert(mcp_backend).values(
        id="b1", owner_login="alice", namespace="rag", name="RAG",
        url="https://rag/mcp", transport="streamable_http", enabled=True))
    await db_conn.execute(insert(mcp_backend).values(
        id="b2", owner_login="alice", namespace="docs", name="Docs",
        url="https://docs/mcp", transport="streamable_http", enabled=False))
    rows = await list_all_enabled_backends(db_conn)
    ids = {r["id"] for r in rows}
    assert ids == {"b1"}  # b2 disabled exclu
```

Ajouter à `backend/tests/mcp/test_monitor.py` (imports DB + faux backend) :

```python
import uuid
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.connections import BackendUnavailable  # noqa: ajuster le chemin réel
from portal.db.tables import mcp_backend, users
from portal.mcp.monitor import monitor_backend_once


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
    await conn.execute(insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4())))
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


async def test_monitor_backend_once_down(db_conn: AsyncConnection) -> None:
    reset_health()
    backend = await _seed_backend(db_conn)

    @asynccontextmanager
    async def _unavailable(url: str, *, bearer: str | None = None, **kw):
        raise BackendUnavailable("down", backend_id="b1")
        yield  # noqa: unreachable, fait du factory un générateur

    health = await monitor_backend_once(db_conn, backend, open_session_fn=_unavailable)
    assert health.status == "down" and health.error is not None
    assert get_health("b1").status == "down"
```

> Note implémenteur : le chemin réel de `BackendUnavailable` est `portal.mcp.connections` (corriger l'import du squelette ci-dessus). Reuse `reset_health`/`get_health` déjà importés (Task 1).

- [ ] **Step 2: Lancer (rouge)**

Run: `cd /d/srcs/devpod-ui/backend && uv run pytest tests/mcp/test_monitor.py tests/db/test_mcp.py -v`
Expected : échec d'import (`list_all_enabled_backends` / `monitor_backend_once` absents).

- [ ] **Step 3: Implémenter**

Dans `backend/src/portal/db/mcp.py`, ajouter (le `select`, `mcp_backend`, colonnes sont déjà importés/utilisés par `list_backends` — réutiliser le même jeu de colonnes) :

```python
async def list_all_enabled_backends(conn: AsyncConnection) -> list[dict[str, Any]]:
    """Tous les backends enabled (tous owners) — usage monitoring système."""
    rows = (
        await conn.execute(
            select(
                mcp_backend.c.id, mcp_backend.c.owner_login, mcp_backend.c.namespace,
                mcp_backend.c.name, mcp_backend.c.url, mcp_backend.c.transport,
                mcp_backend.c.enabled,
            ).where(mcp_backend.c.enabled.is_(True))
        )
    ).mappings().all()
    return [dict(r) for r in rows]
```

Dans `backend/src/portal/mcp/monitor.py`, ajouter les imports et fonctions :

```python
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.catalog import sync_backend  # ajuster : from portal.mcp.catalog import sync_backend
from portal.db.mcp import get_backend_key_secret, list_backend_keys
from portal.mcp.connections import BackendUnavailable, open_session
from portal.mcp.runtime_secrets import UnresolvableSecret, resolve_grant_key

log = structlog.get_logger(__name__)


async def _resolve_monitor_bearer(conn: AsyncConnection, backend_id: str) -> str | None:
    """Première clé enabled dont le secret se résout au runtime, sinon None (best-effort)."""
    for key in await list_backend_keys(conn, backend_id):
        if not key["enabled"]:
            continue
        key_row = await get_backend_key_secret(conn, backend_id, key["id"])
        try:
            secret = await resolve_grant_key(key_row)
        except UnresolvableSecret:
            continue
        if secret is not None:
            return secret.reveal()
    return None


async def monitor_backend_once(
    conn: AsyncConnection, backend_row: dict[str, Any], *, open_session_fn: Any | None = None
) -> BackendHealth:
    """Synchronise le catalogue d'un backend et en déduit sa santé (up/down)."""
    session_fn = open_session_fn if open_session_fn is not None else open_session
    bearer = await _resolve_monitor_bearer(conn, backend_row["id"])
    try:
        async with session_fn(backend_row["url"], bearer=bearer) as session:
            await sync_backend(conn, backend_id=backend_row["id"], session=session)
        health = BackendHealth(status="up")
    except BackendUnavailable as exc:
        health = BackendHealth(status="down", error=str(exc))
    set_health(backend_row["id"], health)
    return health
```

(Corriger les imports `from portal.mcp.catalog import sync_backend`.)

- [ ] **Step 4: Vert + lint**

Run: `cd /d/srcs/devpod-ui/backend && uv run pytest tests/mcp/test_monitor.py tests/db/test_mcp.py -v` → tests purs PASS ; DB SKIPPED.
Run: `cd /d/srcs/devpod-ui/backend && uv run ruff check src/portal/mcp/monitor.py src/portal/db/mcp.py tests/mcp/test_monitor.py tests/db/test_mcp.py && uv run mypy src/portal/mcp/monitor.py src/portal/db/mcp.py` → propre.

- [ ] **Step 5: Commit**

```bash
cd /d/srcs/devpod-ui && git add backend/src/portal/mcp/monitor.py backend/src/portal/db/mcp.py backend/tests/mcp/test_monitor.py backend/tests/db/test_mcp.py
git commit -m "feat(mcp): monitor_backend_once (sync → santé up/down) + list_all_enabled_backends"
```

---

### Task 3 : Enrichir `gateway__list_backends` avec la santé

**Files:**
- Modify: `backend/src/portal/mcp/handlers.py` (`_gateway_list_backends`)
- Test: `backend/tests/mcp/test_server.py`

**Interfaces:**
- Consumes: `monitor.get_health`.
- Produces: `_gateway_list_backends` ajoute `"health"` (le `status`) à chaque entrée du payload JSON.

- [ ] **Step 1: Test rouge**

Ajouter à `backend/tests/mcp/test_server.py` :

```python
async def test_gateway_list_backends_includes_health(db_conn: AsyncConnection) -> None:
    from portal.mcp.handlers import execute_tool_call, GATEWAY_LIST_BACKENDS
    from portal.mcp.monitor import BackendHealth, reset_health, set_health
    import json

    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_tool(db_conn)  # backend b1 ns=rag, grant ak1
    reset_health()
    set_health("b1", BackendHealth(status="up"))

    result = await execute_tool_call(
        db_conn, apikey_id="ak1", owner_login="alice",
        name=GATEWAY_LIST_BACKENDS, arguments={},
        open_session_fn=_patched_open_session(_fake_backend()),
    )
    payload = json.loads(result.content[0].text)
    rag = next(b for b in payload if b["namespace"] == "rag")
    assert rag["health"] == "up"
```

> Note : réutiliser les helpers existants `_seed_apikey`, `_seed_backend_with_tool`, `_fake_backend`, `_patched_open_session` de `test_server.py`.

- [ ] **Step 2: Lancer (rouge)**

Run: `cd /d/srcs/devpod-ui/backend && uv run pytest tests/mcp/test_server.py::test_gateway_list_backends_includes_health -v`
Expected : DB skip local → pas de rouge local exécutable ; le rouge réel est CI Docker. Vérifier que la collection passe (pas d'erreur d'import). **Procéder** ; documenter le TDD partiel DB-only.

- [ ] **Step 3: Implémenter**

Dans `backend/src/portal/mcp/handlers.py`, importer `from portal.mcp.monitor import get_health` et modifier `_gateway_list_backends` :

```python
async def _gateway_list_backends(
    conn: AsyncConnection, owner_login: str
) -> types.CallToolResult:
    backends = await list_backends(conn, owner_login)
    payload = [
        {
            "namespace": b["namespace"],
            "name": b["name"],
            "enabled": b["enabled"],
            "health": get_health(b["id"]).status,
        }
        for b in backends
    ]
    text = json.dumps(payload)
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)])
```

- [ ] **Step 4: Vert + lint**

Run: `cd /d/srcs/devpod-ui/backend && uv run ruff check src/portal/mcp/handlers.py tests/mcp/test_server.py && uv run mypy src/portal/mcp/handlers.py` → propre.
Run: `cd /d/srcs/devpod-ui/backend && uv run pytest tests/mcp -q` → purs PASS, DB skip, 0 warning. `handlers.py` ≤ 300 lignes.

- [ ] **Step 5: Commit**

```bash
cd /d/srcs/devpod-ui && git add backend/src/portal/mcp/handlers.py backend/tests/mcp/test_server.py
git commit -m "feat(mcp): gateway__list_backends expose la santé des backends"
```

---

### Task 4 : `run_monitor_pass` + `monitor_loop` + lifespan + settings

**Files:**
- Modify: `backend/src/portal/mcp/monitor.py` (`run_monitor_pass`, `monitor_loop`)
- Modify: `backend/src/portal/settings.py` (intervalle)
- Modify: `backend/src/portal/app.py` (lifespan : lancer/annuler la tâche)
- Test: `backend/tests/mcp/test_monitor.py`

**Interfaces:**
- Produces:
  - `monitor.run_monitor_pass(*, open_session_fn=None) -> None` — une passe : liste tous les backends enabled, monitore chacun dans sa propre transaction (`_get_engine().begin()`), une erreur par backend est loggée et n'interrompt pas la passe.
  - `monitor.monitor_loop(interval_s: float, *, open_session_fn=None) -> None` — `while True: run_monitor_pass(); await asyncio.sleep(interval_s)` (erreurs de passe loggées, jamais propagées).
  - `settings.AppSettings.mcp_monitor_interval_s: float = 300.0`.
  - `app.py` lifespan : `asyncio.create_task(monitor_loop(...))` lancé après `session_manager.run()`, annulé dans le `finally`.

- [ ] **Step 1: Test rouge (run_monitor_pass, DB)**

Ajouter à `backend/tests/mcp/test_monitor.py` :

```python
async def test_run_monitor_pass_sets_health_for_all_enabled(db_conn: AsyncConnection) -> None:
    """run_monitor_pass utilise le moteur global ; on configure db_conn comme moteur de test."""
    # NOTE: run_monitor_pass ouvre ses propres connexions via _get_engine().begin().
    # Ce test vérifie la LOGIQUE de passe en injectant les backends et un open_session de faux backend.
    # Variante testable : appeler run_monitor_pass avec le moteur testcontainers configuré par db_engine.
    ...
```

> Note implémenteur : `run_monitor_pass` ouvre ses propres connexions via `_get_engine()`. Pour le tester proprement, utilise la fixture `db_engine` (qui configure `_engine` global testcontainers) plutôt que `db_conn` : seed les backends via `async with db_engine.begin()`, puis `await run_monitor_pass(open_session_fn=_patched_open_session(_fake_backend()))`, puis assert `get_health("b1").status == "up"`. Écris ce test concret en remplaçant le squelette ci-dessus, en t'inspirant de `test_server_asgi.py` qui utilise déjà `db_engine`. Si une erreur backend doit être tolérée, ajoute un 2e backend avec un `open_session_fn` qui lève pour lui et vérifie que la passe continue (l'autre est `up`).

- [ ] **Step 2: Lancer (rouge)**

Run: `cd /d/srcs/devpod-ui/backend && uv run pytest tests/mcp/test_monitor.py -v`
Expected : échec d'import (`run_monitor_pass` absent).

- [ ] **Step 3: Implémenter**

Dans `backend/src/portal/mcp/monitor.py`, ajouter `import asyncio`, `from portal.db.engine import _get_engine`, `from portal.db.mcp import list_all_enabled_backends`, puis :

```python
async def run_monitor_pass(*, open_session_fn: Any | None = None) -> None:
    """Une passe de monitoring sur tous les backends enabled (chacun en transaction isolée)."""
    async with _get_engine().connect() as conn:
        backends = await list_all_enabled_backends(conn)
    for backend in backends:
        try:
            async with _get_engine().begin() as conn:
                await monitor_backend_once(conn, backend, open_session_fn=open_session_fn)
        except Exception as exc:  # une erreur backend n'interrompt pas la passe
            log.warning("mcp_monitor_backend_failed", backend_id=backend["id"], error=str(exc))


async def monitor_loop(interval_s: float, *, open_session_fn: Any | None = None) -> None:
    """Boucle de fond : monitore tous les backends toutes les interval_s secondes."""
    while True:
        try:
            await run_monitor_pass(open_session_fn=open_session_fn)
        except Exception as exc:  # noqa: BLE001 — une boucle de fond ne doit jamais mourir
            log.exception("mcp_monitor_pass_failed", error=str(exc))
        await asyncio.sleep(interval_s)
```

Dans `backend/src/portal/settings.py`, ajouter au modèle `AppSettings` (à côté des autres champs) :

```python
    mcp_monitor_interval_s: float = 300.0
```

Dans `backend/src/portal/app.py`, dans le lifespan, lancer la tâche après `session_manager.run()` et l'annuler proprement. Repérer la structure `async with app.state.mcp_session_manager.run(): yield` et la remplacer par :

```python
import asyncio
import contextlib
from portal.mcp.monitor import monitor_loop
# ... (settings déjà accessibles dans app.py via le pattern existant)

async with app.state.mcp_session_manager.run():
    _monitor_task = asyncio.create_task(
        monitor_loop(settings.mcp_monitor_interval_s)
    )
    try:
        yield
    finally:
        _monitor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _monitor_task
```

> Note implémenteur : `settings` doit être l'instance d'`AppSettings` déjà utilisée dans `app.py` (suivre le pattern existant — ne pas réinstancier inutilement). `asyncio`/`contextlib` peuvent déjà être importés.

- [ ] **Step 4: Vérifier (construction + tests)**

Run: `cd /d/srcs/devpod-ui/backend && uv run ruff check src/portal/mcp/monitor.py src/portal/settings.py src/portal/app.py tests/mcp/test_monitor.py && uv run mypy src/portal/mcp/monitor.py src/portal/settings.py src/portal/app.py` → propre.
Run: `cd /d/srcs/devpod-ui/backend && uv run pytest tests/mcp -q` → purs/in-memory PASS, DB skip, 0 warning. `monitor.py` ≤ 300 lignes.
Run (construction, peut échouer sous Windows sur `fcntl` pré-existant — sinon ok) : `cd /d/srcs/devpod-ui/backend && uv run python -c "from portal.app import create_app; create_app(); print('ok')"`. Si l'échec est `fcntl` (pré-existant), c'est attendu ; le montage réel est validé en CI Docker.

- [ ] **Step 5: Commit**

```bash
cd /d/srcs/devpod-ui && git add backend/src/portal/mcp/monitor.py backend/src/portal/settings.py backend/src/portal/app.py backend/tests/mcp/test_monitor.py
git commit -m "feat(mcp): boucle de monitoring (refresh TTL + santé) câblée dans le lifespan"
```

---

## Validation finale du plan

- [ ] `cd /d/srcs/devpod-ui/backend && uv run ruff check src/portal/mcp src/portal/db src/portal/settings.py src/portal/app.py tests/mcp tests/db` → propre.
- [ ] `cd /d/srcs/devpod-ui/backend && uv run mypy src/portal/mcp src/portal/app.py` → propre.
- [ ] `cd /d/srcs/devpod-ui/backend && uv run pytest tests/mcp tests/db -q` → purs/in-memory verts, DB skip, 0 warning.
- [ ] Push → **CI Docker** : tests réels (list_all_enabled_backends, monitor_backend_once up/down, gateway health, run_monitor_pass). Tout vert.
- [ ] Mettre à jour `.superpowers/sdd/progress-runtime.md` (journal Plan 6).

## Couverture spec (auto-review)

- §11 refresh catalogue (TTL de secours) : `monitor_loop` + `run_monitor_pass` + `monitor_backend_once`→`sync_backend` (Tasks 2, 4).
- §11 health check périodique par backend + signalé indisponible dans `gateway__list_backends` : registre santé + enrichissement (Tasks 1, 3) ; `down` sur `BackendUnavailable`.
- §11 démarrage : tâche lancée dans le lifespan, annulée au shutdown (Task 4).
- §6 résolution clé pour le monitoring (best-effort) : `_resolve_monitor_bearer` (Task 2) ; aucun secret loggé.
- **Hors de ce lot (acté)** : refresh sur `list_changed` (push backend→gateway) → nécessite sessions longues (`BackendSessionManager`), différé ; push serveur→client `list_changed` → HORS D'ATTEINTE SDK 1.28 (LESSONS), alternative polling frontend (Plan 7) ; reconnexion = implicite (open_session retente à chaque passe).
