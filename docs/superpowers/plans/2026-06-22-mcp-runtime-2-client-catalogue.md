# MCP Runtime — Plan 2 : Client MCP backend & Catalogue — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Doter la passerelle d'un client MCP capable de se connecter à un backend (Streamable HTTP), d'énumérer ses primitives (tools/resources/prompts) et d'appeler ses tools, puis de synchroniser ces primitives dans le catalogue persistant avec détection de redéfinition (anti rug-pull).

**Architecture:** Trois modules dans `portal/mcp/`. `client.py` porte la logique MCP **sur une `ClientSession` injectée** (testable in-memory, sans réseau). `connections.py` ouvre la vraie session réseau vers un backend (SDK `mcp` Streamable HTTP). `catalog.py` orchestre la synchronisation d'un backend vers `mcp_tool_catalog` (couche DB du Plan 1). La résolution de la clé/bearer et l'agrégation viennent au Plan 3.

**Tech Stack:** Python 3.12, SDK `mcp` 1.28 (`ClientSession`, `streamablehttp_client`, `FastMCP`, `mcp.types`), SQLAlchemy Core, pytest + testcontainers.

**Spec:** `docs/superpowers/specs/2026-06-22-mcp-runtime-design.md` (§4 connections, §5 catalogue, §9.1 list, §11 rug-pull, §12 résilience).

## Global Constraints

- Branche `dev` ; commits conventionnels FR. `from __future__ import annotations` ; type hints partout.
- pydantic v2 ; SQLAlchemy Core ; fichiers ≤ 300 lignes ; logs structlog sans secret.
- API SDK `mcp` 1.28 (confirmée) : `from mcp import ClientSession` ; `from mcp.client.streamable_http import streamablehttp_client` (context manager `async with streamablehttp_client(url, headers=...) as (read, write, _get_sid)`) ; `from mcp.server.fastmcp import FastMCP` ; `from mcp.shared.memory import create_connected_server_and_client_session` (test in-memory, accepte un `FastMCP`). Types : `ListToolsResult.tools` (`Tool.name/description/inputSchema`), `ListResourcesResult.resources` (`Resource.uri/name`), `ListPromptsResult.prompts` (`Prompt.name`), `CallToolResult.content/isError`. Capabilities via `session.get_server_capabilities()` → `.tools/.resources/.prompts` (None si non supporté).
- TDD : test rouge → vert → commit. Les tests **client/catalogue-logique** sont in-memory et **doivent passer en local** (pas de Docker). Les tests touchant `db_conn` SKIP local, validés CI Docker (`test.yml`). Sortie pristine (0 warning), pas de `pytestmark` (asyncio_mode=auto).
- Validation locale par tâche : `uv run ruff check <fichiers>`, `uv run mypy <fichiers src>`, `uv run pytest <tests> -v`.

---

## File Structure

| Fichier | Responsabilité |
|---|---|
| `backend/src/portal/mcp/client.py` (créer) | Logique MCP sur une `ClientSession` : énumérer/normaliser les primitives, appeler un tool |
| `backend/src/portal/mcp/connections.py` (créer) | Ouverture d'une session réseau vers un backend (Streamable HTTP) + erreurs |
| `backend/src/portal/mcp/catalog.py` (créer) | Sync d'un backend → `mcp_tool_catalog` (upsert + prune + quarantaine) |
| `backend/tests/mcp/test_client.py` (créer) | Test in-memory (faux FastMCP) |
| `backend/tests/mcp/test_connections.py` (créer) | Test d'erreur (backend injoignable) + nominal ASGI |
| `backend/tests/mcp/test_catalog.py` (créer) | Sync (faux backend in-memory + db_conn) |

---

## Task 1 : `client.py` — énumération & appel sur une ClientSession

**Files:**
- Create: `backend/src/portal/mcp/client.py`
- Test: `backend/tests/mcp/test_client.py`

**Interfaces:**
- Produces:
  - `def hash_definition(definition: dict) -> str` — sha256 du JSON canonique (sort_keys, séparateurs compacts)
  - `async def fetch_primitives(session: ClientSession) -> list[dict]` — retourne `[{"kind","original_name","definition","definition_hash"}]` pour tools (kind="tool", original_name=name), resources (kind="resource", original_name=str(uri)), prompts (kind="prompt", original_name=name). N'énumère que les familles supportées (capabilities).
  - `async def call_backend_tool(session: ClientSession, name: str, arguments: dict) -> CallToolResult`

- [ ] **Step 1 : Écrire le test in-memory**

Créer `backend/tests/mcp/test_client.py` :

```python
from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from portal.mcp.client import call_backend_tool, fetch_primitives, hash_definition


def _demo_server() -> FastMCP:
    srv = FastMCP("demo")

    @srv.tool()
    def echo(text: str) -> str:
        """Echo le texte."""
        return text

    @srv.resource("demo://greeting")
    def greeting() -> str:
        return "hello"

    @srv.prompt()
    def hi(name: str) -> str:
        return f"Bonjour {name}"

    return srv


def test_hash_definition_stable_and_order_independent() -> None:
    a = hash_definition({"name": "x", "v": 1})
    b = hash_definition({"v": 1, "name": "x"})
    assert a == b
    assert a != hash_definition({"name": "x", "v": 2})


async def test_fetch_primitives_normalizes_all_kinds() -> None:
    async with create_connected_server_and_client_session(_demo_server()) as session:
        await session.initialize()
        prims = await fetch_primitives(session)

    kinds = {p["kind"] for p in prims}
    assert kinds == {"tool", "resource", "prompt"}
    tool = next(p for p in prims if p["kind"] == "tool")
    assert tool["original_name"] == "echo"
    assert isinstance(tool["definition"], dict) and tool["definition_hash"]
    # le hash correspond à la définition normalisée
    assert tool["definition_hash"] == hash_definition(tool["definition"])
    res = next(p for p in prims if p["kind"] == "resource")
    assert res["original_name"] == "demo://greeting"
    prompt = next(p for p in prims if p["kind"] == "prompt")
    assert prompt["original_name"] == "hi"


async def test_call_backend_tool() -> None:
    async with create_connected_server_and_client_session(_demo_server()) as session:
        await session.initialize()
        result = await call_backend_tool(session, "echo", {"text": "ping"})
    assert result.isError is False
    # le contenu texte renvoyé contient "ping"
    assert any(getattr(c, "text", "") == "ping" for c in result.content)
```

> Vérification : `create_connected_server_and_client_session` peut déjà appeler `initialize` selon la version ; si le double `initialize` lève, retirer l'appel explicite dans les tests. Confirmer aussi que le décorateur `@srv.resource("demo://greeting")` est la bonne forme (sinon `srv.add_resource(...)`).

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `cd backend && uv run pytest tests/mcp/test_client.py -v`
Expected: FAIL (`ModuleNotFoundError: portal.mcp.client`).

- [ ] **Step 3 : Implémenter `client.py`**

```python
from __future__ import annotations

import hashlib
import json
from typing import Any

from mcp import ClientSession
from mcp.types import CallToolResult


def hash_definition(definition: dict[str, Any]) -> str:
    canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _entry(kind: str, original_name: str, definition: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": kind,
        "original_name": original_name,
        "definition": definition,
        "definition_hash": hash_definition(definition),
    }


async def fetch_primitives(session: ClientSession) -> list[dict[str, Any]]:
    """Énumère les primitives d'un backend, normalisées pour le catalogue.

    N'interroge que les familles annoncées dans les capabilities du serveur
    (un backend tools-only ne supporte pas resources/prompts).
    """
    caps = session.get_server_capabilities()
    out: list[dict[str, Any]] = []

    if caps is not None and caps.tools is not None:
        for tool in (await session.list_tools()).tools:
            d = tool.model_dump(mode="json", exclude_none=True)
            out.append(_entry("tool", tool.name, d))

    if caps is not None and caps.resources is not None:
        for resource in (await session.list_resources()).resources:
            d = resource.model_dump(mode="json", exclude_none=True)
            out.append(_entry("resource", str(resource.uri), d))

    if caps is not None and caps.prompts is not None:
        for prompt in (await session.list_prompts()).prompts:
            d = prompt.model_dump(mode="json", exclude_none=True)
            out.append(_entry("prompt", prompt.name, d))

    return out


async def call_backend_tool(
    session: ClientSession, name: str, arguments: dict[str, Any]
) -> CallToolResult:
    return await session.call_tool(name, arguments)
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run: `cd backend && uv run pytest tests/mcp/test_client.py -v`
Expected: tous passed, 0 warning. (Si l'`initialize` double pose souci, ajuster les tests comme noté.)

- [ ] **Step 5 : Lint + mypy + commit**

```bash
cd backend && uv run ruff check src/portal/mcp/client.py tests/mcp/test_client.py && uv run mypy src/portal/mcp/client.py
cd .. && git add backend/src/portal/mcp/client.py backend/tests/mcp/test_client.py
git commit -m "feat(mcp): client backend — énumération/normalisation des primitives + call_tool"
```

---

## Task 2 : `connections.py` — session réseau vers un backend

**Files:**
- Create: `backend/src/portal/mcp/connections.py`
- Test: `backend/tests/mcp/test_connections.py`

**Interfaces:**
- Consumes: `streamablehttp_client`, `ClientSession`.
- Produces:
  - `class BackendUnavailable(Exception)` (avec `backend_id` optionnel en attribut)
  - `@asynccontextmanager async def open_session(url: str, *, bearer: str | None = None, timeout_s: float = 30.0) -> AsyncIterator[ClientSession]` — ouvre la session Streamable HTTP, injecte `Authorization: Bearer <bearer>` si fourni, fait `initialize`, yield la session ; convertit toute erreur de connexion/initialize en `BackendUnavailable`.

- [ ] **Step 1 : Écrire les tests**

Créer `backend/tests/mcp/test_connections.py` :

```python
from __future__ import annotations

import pytest

from portal.mcp.connections import BackendUnavailable, open_session


async def test_open_session_unreachable_raises_backend_unavailable() -> None:
    # port fermé / hôte injoignable → BackendUnavailable, pas une exception brute
    with pytest.raises(BackendUnavailable):
        async with open_session("http://127.0.0.1:1/mcp", timeout_s=2.0):
            pass
```

> Test nominal (round-trip réseau) : un test d'intégration montant un `FastMCP.streamable_http_app()` via `httpx.ASGITransport` + `streamablehttp_client(..., httpx_client_factory=...)` est possible mais fragile selon la version du SDK. L'implémenteur PEUT l'ajouter s'il y parvient simplement ; sinon le chemin nominal de `open_session` est exercé de bout en bout au Plan 3 (serveur frontal → backend). Documenter le choix dans le rapport. Ne pas bloquer la tâche sur ce test nominal.

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `cd backend && uv run pytest tests/mcp/test_connections.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3 : Implémenter `connections.py`**

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

_log = structlog.get_logger(__name__)


class BackendUnavailable(Exception):
    """Le backend MCP est injoignable ou a échoué à l'initialisation."""

    def __init__(self, message: str, *, backend_id: str | None = None) -> None:
        super().__init__(message)
        self.backend_id = backend_id


@asynccontextmanager
async def open_session(
    url: str, *, bearer: str | None = None, timeout_s: float = 30.0
) -> AsyncIterator[ClientSession]:
    """Ouvre une session MCP Streamable HTTP vers un backend, initialisée.

    Injecte un bearer token si fourni. Toute erreur de connexion ou
    d'initialisation est convertie en BackendUnavailable (le runtime exclut
    alors le backend sans faire échouer l'agrégation globale).
    """
    from datetime import timedelta

    headers = {"Authorization": f"Bearer {bearer}"} if bearer else None
    try:
        async with streamablehttp_client(
            url, headers=headers, timeout=timedelta(seconds=timeout_s)
        ) as (read, write, _get_sid):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
    except BackendUnavailable:
        raise
    except Exception as exc:
        _log.warning("mcp_backend_unavailable", url=url, error=type(exc).__name__)
        raise BackendUnavailable(f"backend injoignable: {type(exc).__name__}") from exc
```

> Note : `timeout` de `streamablehttp_client` attend un `timedelta` (confirmé par signature `timeout`). Si la version installée attend un float, adapter (le rapport de Plan 1 / Task 1 documente la version `mcp` 1.28).

- [ ] **Step 4 : Lancer, vérifier le succès**

Run: `cd backend && uv run pytest tests/mcp/test_connections.py -v`
Expected: passed (le cas injoignable lève `BackendUnavailable`), 0 warning.

- [ ] **Step 5 : Lint + mypy + commit**

```bash
cd backend && uv run ruff check src/portal/mcp/connections.py tests/mcp/test_connections.py && uv run mypy src/portal/mcp/connections.py
cd .. && git add backend/src/portal/mcp/connections.py backend/tests/mcp/test_connections.py
git commit -m "feat(mcp): connexion réseau vers un backend (Streamable HTTP) + BackendUnavailable"
```

---

## Task 3 : `catalog.py` — synchronisation d'un backend

**Files:**
- Create: `backend/src/portal/mcp/catalog.py`
- Test: `backend/tests/mcp/test_catalog.py`

**Interfaces:**
- Consumes: `client.fetch_primitives`, `db.mcp_catalog.upsert_primitive`/`prune_absent`/`list_primitives`.
- Produces:
  - `async def sync_backend(conn, *, backend_id: str, session: ClientSession) -> dict` — énumère les primitives via `fetch_primitives`, les upsert dans le catalogue (par `backend_id`), supprime celles disparues (`prune_absent` par kind), retourne `{"synced": int, "quarantined": list[str]}` (noms des primitives mises en quarantaine ce cycle).

- [ ] **Step 1 : Écrire le test (faux backend in-memory + db)**

Créer `backend/tests/mcp/test_catalog.py` :

```python
from __future__ import annotations

import uuid

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp_catalog import list_primitives
from portal.db.tables import mcp_backend, users
from portal.mcp.catalog import sync_backend


def _server() -> FastMCP:
    srv = FastMCP("demo")

    @srv.tool()
    def echo(text: str) -> str:
        return text

    return srv


async def _seed(conn: AsyncConnection) -> None:
    await conn.execute(insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4())))
    await conn.execute(
        insert(mcp_backend).values(
            id="b1", owner_login="alice", namespace="rag", name="RAG",
            url="https://rag/mcp", transport="streamable_http",
        )
    )


async def test_sync_backend_populates_catalog(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    async with create_connected_server_and_client_session(_server()) as session:
        await session.initialize()
        result = await sync_backend(db_conn, backend_id="b1", session=session)

    assert result["synced"] == 1
    assert result["quarantined"] == []
    tools = await list_primitives(db_conn, "b1", "tool")
    assert len(tools) == 1 and tools[0]["original_name"] == "echo"
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `cd backend && uv run pytest tests/mcp/test_catalog.py -v`
Expected: FAIL (module absent) ; SKIP si Docker absent (db_conn) — dans ce cas la collecte échoue d'abord sur l'import, donc FAIL est attendu en local jusqu'à création du module ; après création, le test SKIP en local.

- [ ] **Step 3 : Implémenter `catalog.py`**

```python
from __future__ import annotations

from typing import Any

import structlog
from mcp import ClientSession
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db import mcp_catalog as cat_db
from .client import fetch_primitives

_log = structlog.get_logger(__name__)

_KINDS = ("tool", "resource", "prompt")


async def sync_backend(
    conn: AsyncConnection, *, backend_id: str, session: ClientSession
) -> dict[str, Any]:
    """Synchronise les primitives d'un backend dans mcp_tool_catalog.

    Upsert chaque primitive (détection de redéfinition → quarantaine collante),
    puis supprime du catalogue celles qui ne sont plus publiées.
    """
    primitives = await fetch_primitives(session)

    quarantined: list[str] = []
    present: dict[str, list[str]] = {k: [] for k in _KINDS}
    for p in primitives:
        present[p["kind"]].append(p["original_name"])
        flagged = await cat_db.upsert_primitive(
            conn,
            backend_id=backend_id,
            kind=p["kind"],
            original_name=p["original_name"],
            definition=p["definition"],
            definition_hash=p["definition_hash"],
        )
        if flagged:
            quarantined.append(p["original_name"])

    for kind in _KINDS:
        await cat_db.prune_absent(conn, backend_id, kind, present[kind])

    _log.info("mcp_catalog_synced", backend_id=backend_id, count=len(primitives))
    return {"synced": len(primitives), "quarantined": quarantined}
```

- [ ] **Step 4 : Lancer (SKIP DB local) + lint + mypy**

Run:
```bash
cd backend && uv run pytest tests/mcp/test_catalog.py -v
uv run ruff check src/portal/mcp/catalog.py tests/mcp/test_catalog.py && uv run mypy src/portal/mcp/catalog.py
```
Expected: SKIP en local (Docker), 0 warning ; ruff/mypy OK. Validation réelle sur CI Docker.

- [ ] **Step 5 : Étendre la CI + commit**

Ajouter les nouveaux fichiers/tests aux listes ruff/mypy/pytest de `.github/workflows/test.yml` (section `backend-mcp`) : `src/portal/mcp/` est déjà couvert en glob ; ajouter `tests/mcp/test_client.py tests/mcp/test_connections.py tests/mcp/test_catalog.py` au pytest (déjà couverts si `tests/mcp/` est passé en glob — vérifier la ligne pytest et ajouter `tests/mcp/` complet si nécessaire).

```bash
cd .. && git add backend/src/portal/mcp/catalog.py backend/tests/mcp/test_catalog.py .github/workflows/test.yml
git commit -m "feat(mcp): sync catalogue d'un backend (upsert + prune + quarantaine)"
```

---

## Self-Review

**Couverture spec (Plan 2) :**
- Client MCP backend : initialize/tools/resources/prompts (§9.1, §8.4), call_tool (§8.3) → Task 1 ✓
- Connexion Streamable HTTP + backend injoignable → BackendUnavailable (§12) → Task 2 ✓
- Catalogue : sync, definition_hash, quarantaine collante, prune (§5, §11) → Task 3 ✓
- Capabilities-aware (tools-only backend ne casse pas) → Task 1 ✓
- Hors Plan 2 : résolution clé/bearer + agrégation/serveur frontal (Plan 3), notifications push + pool persistant (Plan 4, différés).

**Placeholders :** notes de vérification explicites (double `initialize` du helper de test ; `timeout` timedelta vs float ; test nominal réseau optionnel en Task 2) — points à confirmer contre le SDK réel, pas des trous.

**Cohérence des types :** `fetch_primitives` retourne `[{kind, original_name, definition, definition_hash}]` consommé tel quel par `sync_backend` → `cat_db.upsert_primitive(... definition=, definition_hash=)` (signature Plan 1 Task 5). `open_session` yield une `ClientSession` consommée par `fetch_primitives`/`sync_backend`. `hash_definition` identique entre client et tests.

**Note pour le Plan 3 :** `sync_backend`/`open_session` ne gèrent pas l'auth du backend — le Plan 3 résout la clé du grant (`get_backend_key_secret` + `resolve_grant_key` du Plan 1, cf. LESSONS) et passe le `bearer` à `open_session`.
