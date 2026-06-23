# MCP Runtime — Plan 4 : Serveur MCP frontal `/mcp` (tools) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exposer un serveur MCP frontal multi-tenant monté sur `/mcp` dans l'app FastAPI, authentifié par apikey Bearer, qui agrège dynamiquement les tools autorisés (`tools/list`) et route les invocations (`tools/call`) vers le bon backend distant avec la bonne clé sortante, en traçant chaque appel dans l'audit.

**Architecture:** Serveur **bas-niveau** `mcp.server.lowlevel.Server` (PAS FastMCP — la liste d'outils varie par apikey, ce que FastMCP ne permet pas). Toute la logique vit dans des **fonctions pures** prenant une `AsyncConnection` (ou des `headers`), testables en DB testcontainers sans transport MCP ; les handlers `@server.list_tools()` / `@server.call_tool()` sont de fins adaptateurs qui lisent le Bearer depuis `server.request_context.request.headers`, ouvrent une connexion via `_get_engine().begin()`, et délèguent aux fonctions pures. Montage via `StreamableHTTPSessionManager` (stateful) démarré dans le lifespan FastAPI + `StreamableHTTPASGIApp` sur `app.mount("/mcp", …)`. Le seul point réseau sortant est `connections.open_session`, injecté en test par un faux backend in-memory.

**Tech Stack:** Python 3.12, SDK `mcp` 1.28.0 (`mcp.server.lowlevel.Server`, `StreamableHTTPSessionManager`, `mcp.types`, `mcp.shared.exceptions.McpError`), FastAPI, SQLAlchemy Core async, pydantic v2, pytest + pytest-asyncio, `asgi-lifespan` (nouvelle dev-dep, Task 6) + `httpx.ASGITransport` pour le smoke test in-process.

## Global Constraints

- `from __future__ import annotations` en tête de chaque fichier.
- Async/await partout ; aucune I/O bloquante dans un handler ; jamais de `subprocess`.
- pydantic v2 `extra="forbid"` sur tout nouveau modèle ; modèles internes immuables `frozen=True`.
- SQLAlchemy Core async ; connexion runtime via `_get_engine().begin()` (transaction auto-commit/rollback) — c'est le pattern unique du repo (`portal/db/engine.py`).
- **Sécurité (non négociable)** : aucun secret loggé ; le bearer sortant n'existe qu'au point d'injection via `Secret.reveal()` ; deny-by-default — un appel non autorisé renvoie une erreur générique « tool not found » SANS révéler l'existence d'un backend (réutiliser `resolve_call` qui renvoie déjà `None`).
- **Auth entrante apikey uniquement** : Bearer `mcpk_…` → `token_hash` (sha256 hex) → `find_apikey_by_hash` (non révoquée) → owner. Bearer absent/invalide → `McpError(ErrorData(code=INVALID_PARAMS, message="missing or invalid API key"))`.
- Fichiers ≤ 300 lignes ; logs structlog (`structlog.get_logger(__name__)`), jamais `print`.
- Branche `dev` ; commits conventionnels FR ; TDD strict (rouge → vert → commit).
- Tests DB skippent en local (Docker absent) → validés sur CI Docker `test.yml`. Sortie de test pristine (0 warning ; `filterwarnings=error::DeprecationWarning` est actif).
- Mapping erreurs (spec §13) : tool inconnu/non autorisé → `METHOD_NOT_FOUND` (message générique) ; clé non résoluble runtime → `INTERNAL_ERROR` + audit `error` ; backend injoignable/timeout → `INTERNAL_ERROR` avec `backend_id` + audit `timeout`/`error` ; erreur métier backend → `CallToolResult(isError=True)` transmis tel quel.

---

## Surface existante consommée (Plans 1-3) — signatures exactes

- `portal.mcp.aggregator.aggregate_primitives(conn, *, apikey_id, owner_login, kind) -> list[AggregatedPrimitive]` — `AggregatedPrimitive` (frozen) : `namespaced_name, kind, backend_id, original_name, definition: dict`.
- `portal.mcp.aggregator.resolve_call(conn, *, apikey_id, owner_login, namespaced_name, kind) -> CallTarget | None` — `CallTarget` (frozen) : `backend_id, original_name, url, transport, backend_key_id: str | None`. `None` = deny-by-default.
- `portal.mcp.connections.open_session(url, *, bearer=None, timeout_s=30.0, sse_read_timeout_s=300.0)` — `@asynccontextmanager`, yields `ClientSession` ; lève `BackendUnavailable` (`portal.mcp.connections.BackendUnavailable`) si injoignable.
- `portal.mcp.client.call_backend_tool(session: ClientSession, name: str, arguments: dict, read_timeout_seconds: timedelta | None = None) -> CallToolResult`.
- `portal.mcp.runtime_secrets.resolve_grant_key(key_row: dict | None) -> Secret | None` — `None` si `key_row` None (backend public) ; lève `UnresolvableSecret` (`portal.mcp.runtime_secrets.UnresolvableSecret`) si non résoluble runtime. `Secret.reveal() -> str`.
- `portal.db.mcp.find_apikey_by_hash(conn, token_hash) -> dict | None` — apikey NON révoquée ; colonnes `id, owner_login, label, revoked, created_at`.
- `portal.db.mcp.get_backend_key_secret(conn, backend_id, key_id) -> dict | None` — `{storage_type, secret_value_local, secret_value_vault_ref}`.
- `portal.db.mcp.list_backends(conn, owner_login) -> list[dict]` — `id, owner_login, namespace, name, url, transport, enabled, created_at, updated_at`.
- `portal.db.mcp_audit.record(conn, *, apikey_id, owner_login, namespaced_name, backend_id, backend_key_id, latency_ms, status, error) -> None` — `status ∈ {ok, error, denied, timeout}`.
- `portal.mcp.service.token_hash(token: str) -> str` — sha256 hex.
- `portal.db.engine._get_engine() -> AsyncEngine` ; pattern : `async with _get_engine().begin() as conn:`.
- Fixture test `db_conn: AsyncConnection` (rollback) ; seeding via `insert(users)`, `insert(mcp_backend)`, `insert_apikey`, `insert_backend_key`, `set_grant`, `upsert_primitive`.
- Faux backend de test : `mcp.server.lowlevel.Server` + `mcp.shared.memory.create_connected_server_and_client_session(server) -> ClientSession` (in-memory, accepte un Server bas-niveau).

**Note de vérification (Task 2)** : confirmer la forme du `definition` stocké pour un tool par `portal.mcp.client.fetch_primitives` (clés `inputSchema`/`description`). `_to_tool` lit ces clés ; les tests seedent des `definition` cohérents.

---

### Task 1 : `extract_bearer` (pur) + `resolve_tenant` (DB)

**Files:**
- Create: `backend/src/portal/mcp/server.py`
- Test: `backend/tests/mcp/test_server.py`

**Interfaces:**
- Produces:
  - `extract_bearer(headers: Mapping[str, str]) -> str | None` — lit l'en-tête `authorization` (insensible à la casse via `Mapping.get` sur `Headers` Starlette, mais on supporte aussi un `dict`), retire le préfixe `Bearer ` (insensible à la casse du schéma), renvoie le token ou `None` si absent/vide/mauvais schéma.
  - `async resolve_tenant(conn, token: str | None) -> dict | None` — `None` si token absent ; sinon `find_apikey_by_hash(conn, token_hash(token))`. Renvoie la ligne apikey (`id, owner_login, …`) ou `None`.

- [ ] **Step 1: Écrire le test rouge**

Créer `backend/tests/mcp/test_server.py` :

```python
from __future__ import annotations

import uuid

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import insert_apikey, revoke_apikey
from portal.db.tables import users
from portal.mcp.server import extract_bearer, resolve_tenant
from portal.mcp.service import token_hash


def test_extract_bearer_parses_header() -> None:
    assert extract_bearer({"authorization": "Bearer mcpk_abc"}) == "mcpk_abc"
    assert extract_bearer({"authorization": "bearer mcpk_abc"}) == "mcpk_abc"


def test_extract_bearer_missing_or_malformed() -> None:
    assert extract_bearer({}) is None
    assert extract_bearer({"authorization": ""}) is None
    assert extract_bearer({"authorization": "Basic xyz"}) is None
    assert extract_bearer({"authorization": "Bearer "}) is None


async def _seed_apikey(conn: AsyncConnection, token: str) -> str:
    await conn.execute(
        insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
    )
    await insert_apikey(
        conn, id="ak1", owner_login="alice", token_hash=token_hash(token), label=""
    )
    return "ak1"


async def test_resolve_tenant_valid_token(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    tenant = await resolve_tenant(db_conn, "mcpk_secret")
    assert tenant is not None
    assert tenant["id"] == "ak1" and tenant["owner_login"] == "alice"


async def test_resolve_tenant_no_token_or_unknown(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    assert await resolve_tenant(db_conn, None) is None
    assert await resolve_tenant(db_conn, "mcpk_wrong") is None


async def test_resolve_tenant_revoked(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await revoke_apikey(db_conn, "alice", "ak1")
    assert await resolve_tenant(db_conn, "mcpk_secret") is None
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd backend && uv run pytest tests/mcp/test_server.py -v`
Expected : échec d'import (`cannot import name 'extract_bearer'`). Les tests purs `extract_bearer` échouent aussi à la collection.

- [ ] **Step 3: Implémenter `extract_bearer` + `resolve_tenant`**

Créer `backend/src/portal/mcp/server.py` :

```python
from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import find_apikey_by_hash
from portal.mcp.service import token_hash

_BEARER_PREFIX = "bearer "


def extract_bearer(headers: Mapping[str, str]) -> str | None:
    """Extrait le token Bearer de l'en-tête Authorization (schéma insensible à la casse)."""
    raw = headers.get("authorization") or headers.get("Authorization")
    if not raw or not raw.lower().startswith(_BEARER_PREFIX):
        return None
    token = raw[len(_BEARER_PREFIX) :].strip()
    return token or None


async def resolve_tenant(conn: AsyncConnection, token: str | None) -> dict[str, object] | None:
    """Résout le token apikey clair en ligne apikey (non révoquée) ou None."""
    if not token:
        return None
    return await find_apikey_by_hash(conn, token_hash(token))
```

- [ ] **Step 4: Lancer les tests (purs PASS / DB skip)**

Run: `cd backend && uv run pytest tests/mcp/test_server.py -v`
Expected (local) : `test_extract_bearer_*` **PASSED** ; les 3 tests DB **SKIPPED**.
Run: `cd backend && uv run ruff check src/portal/mcp/server.py tests/mcp/test_server.py && uv run mypy src/portal/mcp/server.py`
Expected : propre.

- [ ] **Step 5: Commit**

```bash
git add backend/src/portal/mcp/server.py backend/tests/mcp/test_server.py
git commit -m "feat(mcp): serveur frontal — extraction Bearer + résolution tenant apikey"
```

---

### Task 2 : `build_tool_descriptors` (agrégation → `Tool` + tool natif)

**Files:**
- Modify: `backend/src/portal/mcp/server.py`
- Test: `backend/tests/mcp/test_server.py`

**Interfaces:**
- Consumes: `aggregate_primitives`.
- Produces:
  - `GATEWAY_LIST_BACKENDS: str = "gateway__list_backends"`
  - `_native_tools() -> list[types.Tool]` — renvoie le tool natif `gateway__list_backends` (inputSchema vide objet).
  - `async build_tool_descriptors(conn, *, apikey_id: str, owner_login: str) -> list[types.Tool]` — agrège les tools autorisés (namespacés) + concatène les tools natifs.

- [ ] **Step 1: Écrire le test rouge**

Vérifier d'abord la forme du `definition` d'un tool produite par `portal.mcp.client.fetch_primitives` (lire la fonction). `_to_tool` doit lire `definition["inputSchema"]` (fallback `{"type":"object"}`) et `definition.get("description")`. Si `fetch_primitives` utilise une autre clé pour le schéma, adapter `_to_tool` ET le seed du test en conséquence (le signaler dans le rapport).

Ajouter à `backend/tests/mcp/test_server.py` (compléter le bloc d'import depuis `portal.mcp.server` avec `build_tool_descriptors, GATEWAY_LIST_BACKENDS` ; ajouter les imports de seeding) :

```python
from portal.db.mcp import set_grant
from portal.db.mcp_catalog import upsert_primitive
from portal.db.tables import mcp_backend
from portal.mcp.server import GATEWAY_LIST_BACKENDS, build_tool_descriptors


async def _seed_backend_with_tool(conn: AsyncConnection) -> None:
    await conn.execute(
        insert(mcp_backend).values(
            id="b1", owner_login="alice", namespace="rag", name="RAG",
            url="https://rag/mcp", transport="streamable_http",
        )
    )
    await set_grant(conn, apikey_id="ak1", backend_id="b1", backend_key_id=None)
    await upsert_primitive(
        conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "search", "description": "Cherche", "inputSchema": {"type": "object"}},
        definition_hash="h1",
    )


async def test_build_tool_descriptors_namespaces_and_adds_native(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_tool(db_conn)

    tools = await build_tool_descriptors(db_conn, apikey_id="ak1", owner_login="alice")
    names = {t.name for t in tools}
    assert "rag__search" in names
    assert GATEWAY_LIST_BACKENDS in names
    rag = next(t for t in tools if t.name == "rag__search")
    assert rag.description == "Cherche"
    assert rag.inputSchema == {"type": "object"}


async def test_build_tool_descriptors_empty_still_has_native(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    tools = await build_tool_descriptors(db_conn, apikey_id="ak1", owner_login="alice")
    assert [t.name for t in tools] == [GATEWAY_LIST_BACKENDS]
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd backend && uv run pytest tests/mcp/test_server.py -v`
Expected : échec d'import (`cannot import name 'build_tool_descriptors'`).

- [ ] **Step 3: Implémenter**

Dans `backend/src/portal/mcp/server.py`, ajouter les imports en tête et les fonctions :

```python
from typing import Any

from mcp import types

from portal.mcp.aggregator import aggregate_primitives
```

```python
GATEWAY_LIST_BACKENDS = "gateway__list_backends"


def _native_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name=GATEWAY_LIST_BACKENDS,
            description="Liste les backends MCP fédérés accessibles et leur disponibilité.",
            inputSchema={"type": "object", "properties": {}},
        )
    ]


def _to_tool(definition: dict[str, Any], namespaced_name: str) -> types.Tool:
    return types.Tool(
        name=namespaced_name,
        description=definition.get("description"),
        inputSchema=definition.get("inputSchema") or {"type": "object"},
    )


async def build_tool_descriptors(
    conn: AsyncConnection, *, apikey_id: str, owner_login: str
) -> list[types.Tool]:
    """Tools autorisés (namespacés) pour cette apikey + tools natifs gateway."""
    prims = await aggregate_primitives(
        conn, apikey_id=apikey_id, owner_login=owner_login, kind="tool"
    )
    tools = [_to_tool(p.definition, p.namespaced_name) for p in prims]
    tools.extend(_native_tools())
    return tools
```

- [ ] **Step 4: Lancer les tests (DB skip local)**

Run: `cd backend && uv run pytest tests/mcp/test_server.py -v`
Expected (local) : tests purs PASS ; tests DB (dont les 2 nouveaux) SKIPPED.
Run: `cd backend && uv run ruff check src/portal/mcp/server.py tests/mcp/test_server.py && uv run mypy src/portal/mcp/server.py`
Expected : propre.

- [ ] **Step 5: Commit**

```bash
git add backend/src/portal/mcp/server.py backend/tests/mcp/test_server.py
git commit -m "feat(mcp): build_tool_descriptors — tools agrégés namespacés + tool natif gateway"
```

---

### Task 3 : `execute_tool_call` — routage + mapping erreurs (sans audit)

**Files:**
- Modify: `backend/src/portal/mcp/server.py`
- Test: `backend/tests/mcp/test_server.py`

**Interfaces:**
- Consumes: `resolve_call`, `get_backend_key_secret`, `resolve_grant_key`/`UnresolvableSecret`, `open_session`/`BackendUnavailable`, `call_backend_tool`, `list_backends`.
- Produces:
  - `async _gateway_list_backends(conn, owner_login) -> types.CallToolResult` — `CallToolResult` JSON (un `TextContent`) listant les backends de l'owner (`namespace, name, enabled`).
  - `async execute_tool_call(conn, *, apikey_id, owner_login, name, arguments, open_session_fn=open_session) -> types.CallToolResult` — route un appel. Tool natif → gateway. Sinon `resolve_call` ; `None` → `McpError(METHOD_NOT_FOUND)`. Résout la clé (KEK/public) ; `UnresolvableSecret` → `McpError(INTERNAL_ERROR)`. Ouvre la session backend (via `open_session_fn`, point d'injection test) ; `BackendUnavailable` → `McpError(INTERNAL_ERROR)` avec `backend_id`. Forward via `call_backend_tool`, renvoie le `CallToolResult`. `open_session_fn` permet d'injecter un faux backend en test. (L'audit est ajouté en Task 4.)

- [ ] **Step 1: Écrire le test rouge**

Ajouter à `backend/tests/mcp/test_server.py` (imports : `pytest`, `from mcp import types`, `from mcp.server.lowlevel import Server`, `from mcp.shared.exceptions import McpError`, `from mcp.types import METHOD_NOT_FOUND`, `from contextlib import asynccontextmanager`, `from mcp.shared.memory import create_connected_server_and_client_session`, et `execute_tool_call, GATEWAY_LIST_BACKENDS` depuis `portal.mcp.server` ; `insert_backend_key` depuis `portal.db.mcp`) :

```python
def _fake_backend() -> Server:
    srv: Server = Server("fake-backend")

    @srv.list_tools()
    async def _lt() -> list[types.Tool]:
        return [types.Tool(name="search", inputSchema={"type": "object"})]

    @srv.call_tool()
    async def _ct(name: str, arguments: dict) -> list[types.TextContent]:
        return [types.TextContent(type="text", text=f"echo:{arguments.get('q', '')}")]

    return srv


def _patched_open_session(server: Server):
    @asynccontextmanager
    async def _factory(url: str, *, bearer: str | None = None, **kw):
        async with create_connected_server_and_client_session(server) as session:
            yield session

    return _factory


async def test_execute_tool_call_routes_and_forwards(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_tool(db_conn)  # backend public (backend_key_id=None)

    result = await execute_tool_call(
        db_conn, apikey_id="ak1", owner_login="alice",
        name="rag__search", arguments={"q": "hi"},
        open_session_fn=_patched_open_session(_fake_backend()),
    )
    assert result.isError is False
    assert result.content[0].text == "echo:hi"


async def test_execute_tool_call_unknown_raises_method_not_found(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_tool(db_conn)
    with pytest.raises(McpError) as exc:
        await execute_tool_call(
            db_conn, apikey_id="ak1", owner_login="alice",
            name="rag__ghost", arguments={},
            open_session_fn=_patched_open_session(_fake_backend()),
        )
    assert exc.value.error.code == METHOD_NOT_FOUND


async def test_execute_tool_call_native_gateway(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_tool(db_conn)
    result = await execute_tool_call(
        db_conn, apikey_id="ak1", owner_login="alice",
        name=GATEWAY_LIST_BACKENDS, arguments={},
        open_session_fn=_patched_open_session(_fake_backend()),
    )
    assert result.isError is False
    assert "rag" in result.content[0].text
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd backend && uv run pytest tests/mcp/test_server.py -v`
Expected : échec d'import (`cannot import name 'execute_tool_call'`).

- [ ] **Step 3: Implémenter**

Dans `backend/src/portal/mcp/server.py`, ajouter les imports puis les fonctions :

```python
import json

from mcp.shared.exceptions import McpError
from mcp.types import ErrorData, INTERNAL_ERROR, METHOD_NOT_FOUND

from portal.db.mcp import get_backend_key_secret, list_backends
from portal.mcp.aggregator import resolve_call
from portal.mcp.client import call_backend_tool
from portal.mcp.connections import BackendUnavailable, open_session
from portal.mcp.runtime_secrets import UnresolvableSecret, resolve_grant_key
```

```python
async def _gateway_list_backends(
    conn: AsyncConnection, owner_login: str
) -> types.CallToolResult:
    backends = await list_backends(conn, owner_login)
    payload = [
        {"namespace": b["namespace"], "name": b["name"], "enabled": b["enabled"]}
        for b in backends
    ]
    text = json.dumps(payload)
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)])


async def execute_tool_call(
    conn: AsyncConnection,
    *,
    apikey_id: str,
    owner_login: str,
    name: str,
    arguments: dict[str, Any],
    open_session_fn: Any = open_session,
) -> types.CallToolResult:
    """Route un tools/call namespacé vers son backend (deny-by-default + mapping erreurs §13)."""
    if name == GATEWAY_LIST_BACKENDS:
        return await _gateway_list_backends(conn, owner_login)

    target = await resolve_call(
        conn, apikey_id=apikey_id, owner_login=owner_login, namespaced_name=name, kind="tool"
    )
    if target is None:
        raise McpError(ErrorData(code=METHOD_NOT_FOUND, message=f"tool not found: {name}"))

    key_row = (
        await get_backend_key_secret(conn, target.backend_id, target.backend_key_id)
        if target.backend_key_id
        else None
    )
    try:
        secret = await resolve_grant_key(key_row)
    except UnresolvableSecret as exc:
        raise McpError(
            ErrorData(code=INTERNAL_ERROR, message="outbound key not resolvable at runtime")
        ) from exc
    bearer = secret.reveal() if secret else None

    try:
        async with open_session_fn(target.url, bearer=bearer) as session:
            return await call_backend_tool(session, target.original_name, arguments)
    except BackendUnavailable as exc:
        raise McpError(
            ErrorData(code=INTERNAL_ERROR, message=f"backend unavailable: {target.backend_id}")
        ) from exc
```

- [ ] **Step 4: Lancer les tests (DB skip local)**

Run: `cd backend && uv run pytest tests/mcp/test_server.py -v`
Expected (local) : tests purs PASS ; tests DB SKIPPED.
Run: `cd backend && uv run ruff check src/portal/mcp/server.py tests/mcp/test_server.py && uv run mypy src/portal/mcp/server.py`
Expected : propre. Vérifier `server.py` ≤ 300 lignes.

- [ ] **Step 5: Commit**

```bash
git add backend/src/portal/mcp/server.py backend/tests/mcp/test_server.py
git commit -m "feat(mcp): execute_tool_call — routage tools/call + clé sortante + mapping erreurs"
```

---

### Task 4 : Audit exhaustif dans `execute_tool_call`

**Files:**
- Modify: `backend/src/portal/mcp/server.py`
- Test: `backend/tests/mcp/test_server.py`

**Interfaces:**
- Consumes: `portal.db.mcp_audit.record`, `time.perf_counter`.
- Produces: `execute_tool_call` écrit **une** ligne d'audit à chaque sortie : `ok` (forward réussi, `isError=False`), `error` (forward `isError=True` OU clé non résoluble), `denied` (tool inconnu/non autorisé), `timeout` (backend injoignable). Latence renseignée pour le chemin forward. Le tool natif gateway audite `ok`.

- [ ] **Step 1: Écrire le test rouge**

Ajouter à `backend/tests/mcp/test_server.py` (import `from portal.db.mcp_audit import list_for_owner`) :

```python
async def test_execute_tool_call_audits_ok(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_tool(db_conn)
    await execute_tool_call(
        db_conn, apikey_id="ak1", owner_login="alice",
        name="rag__search", arguments={"q": "x"},
        open_session_fn=_patched_open_session(_fake_backend()),
    )
    audit = await list_for_owner(db_conn, "alice")
    assert len(audit) == 1
    row = audit[0]
    assert row["status"] == "ok"
    assert row["namespaced_name"] == "rag__search"
    assert row["backend_id"] == "b1"
    assert row["apikey_id"] == "ak1"
    assert row["latency_ms"] is not None


async def test_execute_tool_call_audits_denied(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_tool(db_conn)
    with pytest.raises(McpError):
        await execute_tool_call(
            db_conn, apikey_id="ak1", owner_login="alice",
            name="rag__ghost", arguments={},
            open_session_fn=_patched_open_session(_fake_backend()),
        )
    audit = await list_for_owner(db_conn, "alice")
    assert len(audit) == 1 and audit[0]["status"] == "denied"
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd backend && uv run pytest tests/mcp/test_server.py -v`
Expected : les 2 nouveaux tests, exécutés en DB, SKIPPED en local — donc PAS un vrai rouge local. Pour obtenir un rouge local vérifiable, ce comportement (audit) n'est pas testable sans Docker. **Procéder à l'implémentation** ; le rouge→vert réel se constate en CI Docker. Documenter ce point dans le rapport (TDD partiel : tests d'audit DB-only).

- [ ] **Step 3: Implémenter l'audit**

Modifier `execute_tool_call` dans `backend/src/portal/mcp/server.py`. Ajouter `import time` en tête et `from portal.db.mcp_audit import record as audit_record`. Réécrire le corps pour tracer chaque sortie :

```python
async def execute_tool_call(
    conn: AsyncConnection,
    *,
    apikey_id: str,
    owner_login: str,
    name: str,
    arguments: dict[str, Any],
    open_session_fn: Any = open_session,
) -> types.CallToolResult:
    """Route un tools/call namespacé vers son backend (deny-by-default + mapping erreurs §13 + audit)."""
    if name == GATEWAY_LIST_BACKENDS:
        result = await _gateway_list_backends(conn, owner_login)
        await audit_record(
            conn, apikey_id=apikey_id, owner_login=owner_login,
            namespaced_name=name, backend_id=None, backend_key_id=None,
            latency_ms=None, status="ok", error=None,
        )
        return result

    target = await resolve_call(
        conn, apikey_id=apikey_id, owner_login=owner_login, namespaced_name=name, kind="tool"
    )
    if target is None:
        await audit_record(
            conn, apikey_id=apikey_id, owner_login=owner_login,
            namespaced_name=name, backend_id=None, backend_key_id=None,
            latency_ms=None, status="denied", error=None,
        )
        raise McpError(ErrorData(code=METHOD_NOT_FOUND, message=f"tool not found: {name}"))

    key_row = (
        await get_backend_key_secret(conn, target.backend_id, target.backend_key_id)
        if target.backend_key_id
        else None
    )
    try:
        secret = await resolve_grant_key(key_row)
    except UnresolvableSecret as exc:
        await audit_record(
            conn, apikey_id=apikey_id, owner_login=owner_login,
            namespaced_name=name, backend_id=target.backend_id,
            backend_key_id=target.backend_key_id, latency_ms=None,
            status="error", error="key not resolvable",
        )
        raise McpError(
            ErrorData(code=INTERNAL_ERROR, message="outbound key not resolvable at runtime")
        ) from exc
    bearer = secret.reveal() if secret else None

    started = time.perf_counter()
    try:
        async with open_session_fn(target.url, bearer=bearer) as session:
            result = await call_backend_tool(session, target.original_name, arguments)
    except BackendUnavailable as exc:
        await audit_record(
            conn, apikey_id=apikey_id, owner_login=owner_login,
            namespaced_name=name, backend_id=target.backend_id,
            backend_key_id=target.backend_key_id, latency_ms=None,
            status="timeout", error=str(exc),
        )
        raise McpError(
            ErrorData(code=INTERNAL_ERROR, message=f"backend unavailable: {target.backend_id}")
        ) from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    await audit_record(
        conn, apikey_id=apikey_id, owner_login=owner_login,
        namespaced_name=name, backend_id=target.backend_id,
        backend_key_id=target.backend_key_id, latency_ms=latency_ms,
        status="error" if result.isError else "ok",
        error=None,
    )
    return result
```

- [ ] **Step 4: Vérifier (lint/type + skip local)**

Run: `cd backend && uv run ruff check src/portal/mcp/server.py tests/mcp/test_server.py && uv run mypy src/portal/mcp/server.py`
Expected : propre.
Run: `cd backend && uv run pytest tests/mcp/test_server.py -q`
Expected (local) : tests purs PASS ; tous les tests DB (dont audit) SKIPPED, 0 warning. Vérifier `server.py` ≤ 300 lignes.

- [ ] **Step 5: Commit**

```bash
git add backend/src/portal/mcp/server.py backend/tests/mcp/test_server.py
git commit -m "feat(mcp): audit exhaustif des tools/call (ok/denied/error/timeout + latence)"
```

---

### Task 5 : Assemblage `build_server` + montage `/mcp` dans `app.py`

**Files:**
- Modify: `backend/src/portal/mcp/server.py`
- Modify: `backend/src/portal/app.py`
- Test: (couvert par le smoke test ASGI de la Task 6 — pas de test unitaire de wiring ici)

**Interfaces:**
- Consumes: `mcp.server.lowlevel.Server`, `mcp.server.streamable_http_manager.StreamableHTTPSessionManager`, `mcp.server.fastmcp.server.StreamableHTTPASGIApp`, `_get_engine`, `extract_bearer`, `resolve_tenant`, `build_tool_descriptors`, `execute_tool_call`.
- Produces:
  - `build_server() -> tuple[Server, StreamableHTTPSessionManager]` — instancie le `Server` bas-niveau, enregistre les handlers `list_tools`/`call_tool` (auth Bearer + conn `_get_engine().begin()` + délégation aux fonctions pures), et un `StreamableHTTPSessionManager(app=server, stateless=False)`.
  - `app.py` : monte `app.mount("/mcp", StreamableHTTPASGIApp(session_manager))` et démarre `session_manager.run()` dans le lifespan.

- [ ] **Step 1: Implémenter `build_server`**

Dans `backend/src/portal/mcp/server.py`, ajouter en tête `import structlog`, les imports SDK serveur, et `from portal.db.engine import _get_engine`. Ajouter :

```python
log = structlog.get_logger(__name__)

_UNAUTHORIZED = ErrorData(code=INVALID_PARAMS, message="missing or invalid API key")
```

(ajouter `INVALID_PARAMS` à l'import `from mcp.types import ...`.) Puis :

```python
def build_server() -> tuple[Server, "StreamableHTTPSessionManager"]:
    """Construit le serveur MCP frontal bas-niveau + son gestionnaire de sessions."""
    server: Server = Server("workspace-portal-mcp")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        req = server.request_context.request
        token = extract_bearer(req.headers if req is not None else {})
        async with _get_engine().begin() as conn:
            tenant = await resolve_tenant(conn, token)
            if tenant is None:
                raise McpError(_UNAUTHORIZED)
            return await build_tool_descriptors(
                conn, apikey_id=str(tenant["id"]), owner_login=str(tenant["owner_login"])
            )

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> types.CallToolResult:
        req = server.request_context.request
        token = extract_bearer(req.headers if req is not None else {})
        async with _get_engine().begin() as conn:
            tenant = await resolve_tenant(conn, token)
            if tenant is None:
                raise McpError(_UNAUTHORIZED)
            return await execute_tool_call(
                conn, apikey_id=str(tenant["id"]), owner_login=str(tenant["owner_login"]),
                name=name, arguments=arguments or {},
            )

    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    manager = StreamableHTTPSessionManager(app=server, stateless=False)
    return server, manager
```

> **Note implémenteur** : la duplication de l'extraction Bearer + résolution tenant entre les deux handlers (4 lignes) est acceptable — la connexion doit rester ouverte pendant tout le handler (le `async with _get_engine().begin()` ne peut pas être sorti du handler sans générateur). Ne PAS sur-abstraire.

- [ ] **Step 2: Monter dans `app.py`**

Lire `backend/src/portal/app.py` (lifespan `_lifespan` ~l.96-138 ; `create_app`/montage ~l.141-208). Dans `create_app`, après la construction de `app` et avant/après les `include_router`, ajouter :

```python
from mcp.server.fastmcp.server import StreamableHTTPASGIApp

from portal.mcp.server import build_server

# ... dans create_app, après app = FastAPI(...) :
_mcp_server, _mcp_session_manager = build_server()
app.mount("/mcp", StreamableHTTPASGIApp(_mcp_session_manager))
app.state.mcp_session_manager = _mcp_session_manager
```

Dans `_lifespan`, encapsuler le `yield` existant par le run du manager. Repérer le `yield` et l'envelopper :

```python
# avant : yield
async with app.state.mcp_session_manager.run():
    yield
```

(Veiller à ce que `async with session_manager.run()` enveloppe bien le `yield` SANS casser les `async with` existants — il doit être le plus interne, juste autour du `yield`.)

- [ ] **Step 3: Vérifier que l'app démarre (lint/type + import)**

Run: `cd backend && uv run ruff check src/portal/mcp/server.py src/portal/app.py && uv run mypy src/portal/mcp/server.py src/portal/app.py`
Expected : propre.
Run: `cd backend && uv run python -c "from portal.app import create_app; app = create_app(); print('mount ok', any(getattr(r, 'path', '') == '/mcp' for r in app.routes))"`
Expected : `mount ok True` (l'app se construit et la route `/mcp` est montée). Si `_get_engine` n'est pas configuré hors lifespan, l'import/construction ne doit PAS l'exiger (le mount n'ouvre pas de connexion). Si erreur, signaler.

- [ ] **Step 4: Vérifier `server.py` ≤ 300 lignes**

Run: `cd backend && wc -l src/portal/mcp/server.py`
Expected : ≤ 300. Si dépassé, signaler en DONE_WITH_CONCERNS (un split éventuel serait décidé hors de cette tâche).

- [ ] **Step 5: Commit**

```bash
git add backend/src/portal/mcp/server.py backend/src/portal/app.py
git commit -m "feat(mcp): serveur frontal monté sur /mcp (handlers tools + lifespan session manager)"
```

---

### Task 6 : Smoke test d'intégration ASGI (auth Bearer bout-en-bout)

**Files:**
- Modify: `backend/pyproject.toml` (ajouter `asgi-lifespan` aux dev deps)
- Test: `backend/tests/mcp/test_server_asgi.py`

**Interfaces:**
- Consumes: `create_app` (ou un montage minimal), `asgi_lifespan.LifespanManager`, `httpx.ASGITransport`, le client MCP `streamable_http_client` + `create_mcp_http_client` (cf. `connections.py`).

- [ ] **Step 1: Ajouter la dev-dep `asgi-lifespan`**

Dans `backend/pyproject.toml`, repérer le groupe de dépendances de développement (là où figurent `pytest`, `respx`, `testcontainers`). Ajouter `"asgi-lifespan>=2.1"`. Puis :

Run: `cd backend && uv sync`
Expected : résolution OK, `asgi-lifespan` installé.

- [ ] **Step 2: Écrire le smoke test (rouge)**

Créer `backend/tests/mcp/test_server_asgi.py`. Ce test monte un serveur MCP minimal (pas le lifespan complet du portail) pour isoler le chemin auth, en réutilisant `build_server` et un engine de test configuré. Il vérifie : Bearer valide → `initialize` + `tools/list` renvoie le tool natif ; Bearer absent → erreur.

```python
from __future__ import annotations

import uuid

import httpx
import pytest
from asgi_lifespan import LifespanManager
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
from sqlalchemy import insert
from starlette.applications import Starlette

from mcp.server.fastmcp.server import StreamableHTTPASGIApp

from portal.db.mcp import insert_apikey
from portal.db.tables import users
from portal.mcp.server import GATEWAY_LIST_BACKENDS, build_server
from portal.mcp.service import token_hash


def _app() -> Starlette:
    _server, manager = build_server()

    async def _run_lifespan(app):  # Starlette lifespan
        async with manager.run():
            yield

    app = Starlette(lifespan=lambda app: _run_lifespan(app))
    app.mount("/mcp", StreamableHTTPASGIApp(manager))
    return app


async def test_mcp_endpoint_lists_native_tool_with_valid_bearer(db_engine) -> None:
    # db_engine configure le moteur global testcontainers ; on seede une apikey.
    async with db_engine.begin() as conn:
        await conn.execute(
            insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
        )
        await insert_apikey(conn, id="ak1", owner_login="alice",
                            token_hash=token_hash("mcpk_secret"), label="")

    app = _app()
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)

        def _factory(**kwargs):
            kwargs.pop("transport", None)
            return create_mcp_http_client(**kwargs, transport=transport)

        async with streamable_http_client(
            "http://test/mcp",
            http_client=create_mcp_http_client(
                headers={"Authorization": "Bearer mcpk_secret"},
                transport=transport,
            ),
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert any(t.name == GATEWAY_LIST_BACKENDS for t in tools.tools)
```

> **Note implémenteur** : ce test exige plusieurs détails SDK à confirmer contre la version installée :
> 1. La signature de `streamable_http_client` et ce qu'il yield (un tuple `(read, write, ...)`) — cf. l'usage réel dans `backend/src/portal/mcp/connections.py` et copier le pattern EXACT.
> 2. Que `create_mcp_http_client` accepte `transport=` (httpx). Sinon, construire `httpx.AsyncClient(transport=ASGITransport(app=app), headers=..., base_url="http://test")` directement et le passer en `http_client=`.
> 3. Que le moteur global testcontainers est bien celui que `build_server`/handlers utilisent (`_get_engine()`), via la fixture `db_engine` qui fait `_engine_module._engine = engine`. La fixture `db_engine` existe dans `tests/conftest.py`.
>
> Si l'assemblage exact du client streamable HTTP s'avère trop instable in-process, RÉDUIRE ce test à un POST `initialize` brut via `httpx.AsyncClient(transport=ASGITransport(app=app))` (JSON-RPC `{"jsonrpc":"2.0","id":1,"method":"initialize",...}` avec en-tête `Authorization`) et asserter un 200 + corps non-erreur, plutôt que de passer par `ClientSession`. Le but est de prouver que le endpoint monté répond et applique l'auth — pas de re-tester le SDK client. Documenter le choix retenu dans le rapport.

- [ ] **Step 3: Lancer le test**

Run: `cd backend && uv run pytest tests/mcp/test_server_asgi.py -v`
Expected (local) : SKIPPED si Docker absent (le test dépend de `db_engine` testcontainers). Le rouge→vert réel se constate en CI Docker. Si le test n'utilise PAS de DB (variante POST brut sans seed), l'adapter pour rester exécutable ; sinon, DB-only.

- [ ] **Step 4: Vérifier lint/type**

Run: `cd backend && uv run ruff check tests/mcp/test_server_asgi.py && uv run mypy tests/mcp/test_server_asgi.py`
Expected : propre (ajouter `# type: ignore[attr-defined]` ciblé si un symbole SDK sans `__all__` le requiert, comme en Plan 2).

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/tests/mcp/test_server_asgi.py
git commit -m "test(mcp): smoke ASGI in-process du serveur frontal /mcp (auth Bearer)"
```

---

## Validation finale du plan

- [ ] `cd backend && uv run ruff check src/portal/mcp src/portal/app.py tests/mcp` → propre.
- [ ] `cd backend && uv run mypy src/portal/mcp/server.py src/portal/app.py` → propre.
- [ ] `cd backend && uv run pytest tests/mcp -q` → local : tests purs verts, tests DB skipped, 0 warning, 0 erreur d'import.
- [ ] `cd backend && wc -l src/portal/mcp/server.py` ≤ 300.
- [ ] Push → **CI Docker** : exécution réelle des tests serveur (résolution tenant, build_tool_descriptors, execute_tool_call routage/erreurs/audit, smoke ASGI). Tout vert.
- [ ] Mettre à jour `.superpowers/sdd/progress-runtime.md` (journal Plan 4).

## Couverture spec (auto-review)

- §4 / §9.1 endpoint multi-tenant `/mcp`, owner via apikey, `tools/list` agrégé : handlers + `build_tool_descriptors` (Tasks 2, 5).
- §9.1 étape 6 (tools natifs `gateway__*`) : `_native_tools` + `gateway__list_backends` (Tasks 2, 3).
- §9.2 `tools/call` (découpe via `resolve_call`, résolution clé, session, forward, mapping) : `execute_tool_call` (Task 3).
- §6 résolution secret sortant (KEK/public) : `get_backend_key_secret` + `resolve_grant_key` câblés (Task 3) ; `UnresolvableSecret` → erreur + audit (Tasks 3-4).
- §10 auth apikey deny-by-default, pas de fuite d'existence : `resolve_tenant` + `resolve_call`→None→`METHOD_NOT_FOUND` générique (Tasks 1, 3).
- §11 montage dans le process FastAPI, sessions stateful liées à l'auth : `StreamableHTTPSessionManager(stateless=False)` + lifespan (Task 5).
- §13 mapping erreurs complet : Task 3 (+ audit Task 4).
- Audit exhaustif (`mcp_audit_log`) sur ok/denied/error/timeout : Task 4.
- **Hors de ce lot** (rappel roadmap) : `resources/`+`prompts/` (Plan 5) ; notifications `list_changed` + health/résilience/reconnexion + refresh catalogue TTL (Plan 6) ; UI curation par grant (Plan 7). Le tool natif `gateway__list_backends` ne reporte ici que `enabled` ; la disponibilité réseau (santé) est enrichie au Plan 6.
