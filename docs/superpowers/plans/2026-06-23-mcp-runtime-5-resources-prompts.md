# MCP Runtime — Plan 5 : Resources & Prompts frontaux — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Étendre le serveur MCP frontal `/mcp` aux **resources** (`resources/list` + `resources/read`) et **prompts** (`prompts/list` + `prompts/get`), avec agrégation par apikey, namespacing, routage vers le backend distant, et audit — sur le modèle des tools du Plan 4.

**Architecture:** Réutilise toute la fondation des Plans 3-4. Les **prompts** se namespacent comme les tools (`<namespace>__<name>`, `split_namespaced`/`resolve_call` existants). Les **resources** ont une URI comme identifiant — l'underscore étant illégal dans un scheme RFC 3986, on namespace l'URI via un scheme dédié **`gw+{namespace}:///{quote(uri_originale)}`** réversible par une nouvelle fonction `split_namespaced_uri`. Les fonctions de logique restent pures (prennent `conn`), les handlers SDK bas-niveau délèguent. Le seul point réseau (`open_session`) reste injectable pour les tests.

**Tech Stack:** Python 3.12, SDK `mcp` 1.28 (`Server.list_resources/read_resource/list_prompts/get_prompt`, `ReadResourceContents` de `mcp.server.lowlevel.helper_types`, `mcp.types`), SQLAlchemy Core async, pydantic v2 (`AnyUrl`, `TypeAdapter`), pytest. Tests DB/ASGI via testcontainers (skip local → CI Docker), faux backend in-memory via `create_connected_server_and_client_session`.

## Global Constraints

- `from __future__ import annotations` ; async partout ; pas d'I/O bloquant dans un handler.
- pydantic v2 `extra="forbid"` sur tout nouveau modèle ; modèles internes `frozen=True`.
- Conn runtime : `async with _get_engine().connect() as conn:` ; handlers **lecture seule** (list_*) sans commit ; handlers **audités** (read_resource, get_prompt) avec `try/except McpError: await conn.commit(); raise` + `await conn.commit()` au succès (audit durable — leçon Plan 4).
- **Deny-by-default** : resource/prompt inconnu ou non autorisé → `McpError(ErrorData(code=METHOD_NOT_FOUND, message="unknown resource"|"unknown prompt"))`, message générique sans révéler l'existence. Bearer invalide → `McpError(ErrorData(code=INVALID_PARAMS, message="missing or invalid API key"))`.
- **Sécurité** : aucun secret loggé ; bearer sortant seulement via `Secret.reveal()` au point d'injection `open_session`.
- **Audit** (`mcp_audit_log`) : une ligne par `resources/read` et `prompts/get` (ok/denied/error/timeout), `namespaced_name` = l'URI namespacée / le prompt namespacé. Jamais de secret en audit.
- Fichiers ≤ 300 lignes (si `server.py` dépasse, le signaler — split décidé hors tâche).
- Branche `dev` ; commits conventionnels FR ; TDD strict.
- Tests DB/ASGI skippent en local (Docker absent) → CI Docker. Sortie pristine (`filterwarnings=error::DeprecationWarning` actif). Le client MCP doit cibler `/mcp/` (slash final) + `follow_redirects=True` (leçon Plan 4).
- **Écart SDK connu** : un handler `read_resource`/`get_prompt` qui lève une exception est renvoyé par le SDK comme erreur — pour `get_prompt`/`read_resource` (non-tool) le SDK propage en `McpError` côté client (comme `list_tools`), PAS en `isError` (ça, c'est spécifique à `call_tool`). À confirmer en T5 et adapter les assertions ASGI.

---

## Surface existante consommée (Plans 1-4)

- `portal.mcp.aggregator.aggregate_primitives(conn, *, apikey_id, owner_login, kind) -> list[AggregatedPrimitive]` — `kind` ∈ {tool, resource, prompt} ; `AggregatedPrimitive(namespaced_name, kind, backend_id, original_name, definition)`.
- `portal.mcp.aggregator.resolve_call(conn, *, apikey_id, owner_login, namespaced_name, kind) -> CallTarget | None` — `CallTarget(backend_id, original_name, url, transport, backend_key_id)`.
- `portal.mcp.aggregator.split_namespaced(name) -> tuple[str,str] | None` ; `_curation_allows(...)`.
- `portal.mcp.client.fetch_primitives`, `call_backend_tool` ; `portal.mcp.connections.open_session`/`BackendUnavailable` ; `portal.mcp.runtime_secrets.resolve_grant_key`/`UnresolvableSecret`.
- `portal.mcp.server` (Plan 4) : `extract_bearer`, `resolve_tenant`, `execute_tool_call`, `build_tool_descriptors`, `build_server`, `GATEWAY_LIST_BACKENDS`, `_UNAUTHORIZED`, `_get_engine`, audit via `record as audit_record`.
- `portal.db.mcp.get_backend_key_secret`, `list_backends`, `find_apikey_by_hash`, seeding (`insert_apikey`, `insert_backend_key`, `set_grant`), `portal.db.mcp_catalog.upsert_primitive`, `list_primitives`, `portal.db.mcp_audit.record`/`list_for_owner`.
- Faux backend test : `mcp.server.lowlevel.Server` + `mcp.shared.memory.create_connected_server_and_client_session`.

**SDK 1.28 (vérifié)** — formes des handlers : `list_resources()->list[types.Resource]` ; `read_resource(uri: AnyUrl)->Iterable[ReadResourceContents]` (`ReadResourceContents(content: str|bytes, mime_type: str|None)` de `mcp.server.lowlevel.helper_types`) ; `list_prompts()->list[types.Prompt]` ; `get_prompt(name: str, arguments: dict[str,str]|None)->types.GetPromptResult`. Méthodes client : `session.read_resource(uri: AnyUrl)->ReadResourceResult` (`contents: list[TextResourceContents|BlobResourceContents]`), `session.get_prompt(name, arguments)->GetPromptResult`.

---

### Task 1 : `client.py` — `read_backend_resource` + `get_backend_prompt`

**Files:**
- Modify: `backend/src/portal/mcp/client.py`
- Test: `backend/tests/mcp/test_client.py`

**Interfaces:**
- Produces:
  - `async read_backend_resource(session: ClientSession, uri: AnyUrl) -> ReadResourceResult`
  - `async get_backend_prompt(session: ClientSession, name: str, arguments: dict[str, str] | None = None) -> GetPromptResult`

- [ ] **Step 1: Écrire le test rouge**

Ajouter à `backend/tests/mcp/test_client.py` (compléter les imports : `from pydantic import AnyUrl`, et `read_backend_resource, get_backend_prompt` depuis `portal.mcp.client`). Le faux backend doit exposer une resource et un prompt :

```python
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import AnyUrl

from portal.mcp.client import get_backend_prompt, read_backend_resource


def _server_with_resource_and_prompt() -> FastMCP:
    srv = FastMCP("demo")

    @srv.resource("resource://greeting")
    def greeting() -> str:
        return "hello"

    @srv.prompt()
    def welcome(who: str) -> str:
        return f"Welcome {who}"

    return srv


async def test_read_backend_resource() -> None:
    async with create_connected_server_and_client_session(
        _server_with_resource_and_prompt()
    ) as session:
        result = await read_backend_resource(session, AnyUrl("resource://greeting"))
    assert result.contents[0].text == "hello"


async def test_get_backend_prompt() -> None:
    async with create_connected_server_and_client_session(
        _server_with_resource_and_prompt()
    ) as session:
        result = await get_backend_prompt(session, "welcome", {"who": "Bob"})
    assert "Bob" in result.messages[0].content.text
```

> Note implémenteur : vérifier la forme exacte renvoyée par le FastMCP de test (`result.contents[0]` peut être `TextResourceContents` → `.text` ; `result.messages[0].content` est un `TextContent` → `.text`). Adapter l'assertion si la version diffère, en lisant les types réels.

- [ ] **Step 2: Lancer le test (rouge — import)**

Run: `cd /d/srcs/devpod-ui/backend && uv run pytest tests/mcp/test_client.py -v`
Expected : échec d'import (`cannot import name 'read_backend_resource'`). Ces tests in-memory tournent en LOCAL (pas de DB) — ils doivent passer après impl.

- [ ] **Step 3: Implémenter**

Dans `backend/src/portal/mcp/client.py`, ajouter aux imports `from pydantic import AnyUrl` et compléter `from mcp.types import ...` avec `ReadResourceResult, GetPromptResult`. Puis :

```python
async def read_backend_resource(session: ClientSession, uri: AnyUrl) -> ReadResourceResult:
    """Lit une ressource d'un backend ; retourne le résultat brut non transformé."""
    return await session.read_resource(uri)


async def get_backend_prompt(
    session: ClientSession, name: str, arguments: dict[str, str] | None = None
) -> GetPromptResult:
    """Récupère un prompt d'un backend ; retourne le résultat brut non transformé."""
    return await session.get_prompt(name, arguments)
```

- [ ] **Step 4: Vert + lint**

Run: `cd /d/srcs/devpod-ui/backend && uv run pytest tests/mcp/test_client.py -v` → les 2 nouveaux tests **PASSED** (in-memory), le reste inchangé.
Run: `cd /d/srcs/devpod-ui/backend && uv run ruff check src/portal/mcp/client.py tests/mcp/test_client.py && uv run mypy src/portal/mcp/client.py` → propre.

- [ ] **Step 5: Commit**

```bash
cd /d/srcs/devpod-ui && git add backend/src/portal/mcp/client.py backend/tests/mcp/test_client.py
git commit -m "feat(mcp): client — read_backend_resource + get_backend_prompt"
```

---

### Task 2 : Namespacing URI + `namespace` sur `AggregatedPrimitive` + `resolve_resource`

**Files:**
- Modify: `backend/src/portal/mcp/aggregator.py`
- Test: `backend/tests/mcp/test_aggregator.py`

**Interfaces:**
- Produces:
  - `AggregatedPrimitive` gagne un champ `namespace: str`.
  - `make_namespaced_uri(namespace: str, original_uri: str) -> str` → `f"gw+{namespace}:///{quote(original_uri, safe='')}"`.
  - `split_namespaced_uri(uri: str) -> tuple[str, str] | None` → `(namespace, original_uri)` ou `None` si le scheme n'est pas `gw+...`.
  - `_resolve_target(conn, *, apikey_id, owner_login, namespace: str, original: str, kind: str) -> CallTarget | None` — cœur de résolution post-découpe (extrait de `resolve_call`).
  - `resolve_resource(conn, *, apikey_id, owner_login, namespaced_uri: str, kind: str = "resource") -> CallTarget | None`.
  - `resolve_call` inchangé en signature mais réimplémenté via `_resolve_target`.

- [ ] **Step 1: Écrire le test rouge**

Ajouter à `backend/tests/mcp/test_aggregator.py` (imports : `make_namespaced_uri, split_namespaced_uri, resolve_resource`) :

```python
import pytest

from portal.mcp.aggregator import (
    make_namespaced_uri,
    resolve_resource,
    split_namespaced_uri,
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


async def test_resolve_resource_routes(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)  # helper existant : user alice, backend b1 ns=rag enabled, apikey ak1
    await set_grant(db_conn, apikey_id="ak1", backend_id="b1", backend_key_id=None)
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
    await set_grant(db_conn, apikey_id="ak1", backend_id="b1", backend_key_id=None)
    # pas de resource au catalogue → None
    assert await resolve_resource(
        db_conn, apikey_id="ak1", owner_login="alice",
        namespaced_uri=make_namespaced_uri("rag", "resource://ghost"),
    ) is None
    # URI étrangère (non gw+) → None
    assert await resolve_resource(
        db_conn, apikey_id="ak1", owner_login="alice", namespaced_uri="file:///x"
    ) is None
```

Note : si le helper `_seed` existant ne crée pas l'apikey `ak1`, l'ajouter au seed du test (cf. `insert_apikey`).

- [ ] **Step 2: Lancer le test (rouge)**

Run: `cd /d/srcs/devpod-ui/backend && uv run pytest tests/mcp/test_aggregator.py -v`
Expected : échec d'import (`cannot import name 'make_namespaced_uri'`).

- [ ] **Step 3: Implémenter**

Dans `backend/src/portal/mcp/aggregator.py` :

1. Ajouter `from urllib.parse import quote, unquote` en tête.
2. Ajouter le champ `namespace: str` au modèle `AggregatedPrimitive` (après `kind`), et le renseigner dans `aggregate_primitives` (`namespace=namespace`, déjà calculé localement).
3. Ajouter les fonctions URI :

```python
_URI_PREFIX = "gw+"


def make_namespaced_uri(namespace: str, original_uri: str) -> str:
    """URI exposée au client frontal : scheme `gw+<ns>`, URI originale percent-encodée."""
    return f"{_URI_PREFIX}{namespace}:///{quote(original_uri, safe='')}"


def split_namespaced_uri(uri: str) -> tuple[str, str] | None:
    """Inverse de make_namespaced_uri. `None` si l'URI n'est pas une URI gateway."""
    scheme, sep, rest = uri.partition(":///")
    if not sep or not scheme.startswith(_URI_PREFIX):
        return None
    namespace = scheme[len(_URI_PREFIX) :]
    if not namespace:
        return None
    return namespace, unquote(rest)
```

4. Extraire le cœur de `resolve_call` en `_resolve_target` et réimplémenter `resolve_call` + ajouter `resolve_resource` :

```python
async def _resolve_target(
    conn: AsyncConnection, *, apikey_id: str, owner_login: str,
    namespace: str, original: str, kind: str,
) -> CallTarget | None:
    for grant in await list_grants(conn, apikey_id):
        backend = await get_backend(conn, owner_login, grant["backend_id"])
        if backend is None or not backend["enabled"] or backend["namespace"] != namespace:
            continue
        if not _curation_allows(grant["expose_mode"], grant["expose"] or [], original):
            return None
        match = next(
            (p for p in await list_primitives(conn, grant["backend_id"], kind)
             if p["original_name"] == original),
            None,
        )
        if match is None or match["quarantined"]:
            return None
        return CallTarget(
            backend_id=grant["backend_id"], original_name=original,
            url=backend["url"], transport=backend["transport"],
            backend_key_id=grant["backend_key_id"],
        )
    return None


async def resolve_call(
    conn: AsyncConnection, *, apikey_id: str, owner_login: str,
    namespaced_name: str, kind: str,
) -> CallTarget | None:
    parsed = split_namespaced(namespaced_name)
    if parsed is None:
        return None
    namespace, original = parsed
    return await _resolve_target(
        conn, apikey_id=apikey_id, owner_login=owner_login,
        namespace=namespace, original=original, kind=kind,
    )


async def resolve_resource(
    conn: AsyncConnection, *, apikey_id: str, owner_login: str,
    namespaced_uri: str, kind: str = "resource",
) -> CallTarget | None:
    parsed = split_namespaced_uri(namespaced_uri)
    if parsed is None:
        return None
    namespace, original = parsed
    return await _resolve_target(
        conn, apikey_id=apikey_id, owner_login=owner_login,
        namespace=namespace, original=original, kind=kind,
    )
```

5. **Mettre à jour le test Plan 3** `test_aggregate_namespaces_and_excludes_quarantined` qui construit un `AggregatedPrimitive(...)` complet : ajouter `namespace="rag"` à l'objet attendu (sinon il casse avec le nouveau champ requis).

- [ ] **Step 4: Vert + lint**

Run: `cd /d/srcs/devpod-ui/backend && uv run pytest tests/mcp/test_aggregator.py -v` → tests purs (`namespaced_uri_roundtrip`, `split_namespaced_uri_rejects_foreign`) **PASSED** ; tests DB **SKIPPED** ; aucun test Plan 3 cassé (le test mis à jour collecte).
Run: `cd /d/srcs/devpod-ui/backend && uv run ruff check src/portal/mcp/aggregator.py tests/mcp/test_aggregator.py && uv run mypy src/portal/mcp/aggregator.py` → propre. `aggregator.py` ≤ 300 lignes.

- [ ] **Step 5: Commit**

```bash
cd /d/srcs/devpod-ui && git add backend/src/portal/mcp/aggregator.py backend/tests/mcp/test_aggregator.py
git commit -m "feat(mcp): namespacing URI resources (gw+ns) + champ namespace + resolve_resource"
```

---

### Task 3 : Serveur — prompts (`list_prompts` + `get_prompt` + audit)

**Files:**
- Modify: `backend/src/portal/mcp/server.py`
- Test: `backend/tests/mcp/test_server.py`

**Interfaces:**
- Produces:
  - `async build_prompt_descriptors(conn, *, apikey_id, owner_login) -> list[types.Prompt]` — agrège kind="prompt", namespacing `__`.
  - `async execute_prompt_get(conn, *, apikey_id, owner_login, name, arguments, open_session_fn=open_session) -> types.GetPromptResult` — `resolve_call(kind="prompt")` → None → audit denied + `McpError(METHOD_NOT_FOUND, "unknown prompt")` ; clé ; `open_session_fn` → `BackendUnavailable` → audit timeout + INTERNAL_ERROR ; `get_backend_prompt` → audit ok. `UnresolvableSecret` → audit error + INTERNAL_ERROR.

- [ ] **Step 1: Écrire le test rouge**

Ajouter à `backend/tests/mcp/test_server.py` (imports : `build_prompt_descriptors, execute_prompt_get` ; le faux backend `_fake_backend`/`_patched_open_session` existants devront exposer un prompt — ajouter un `@srv.get_prompt`-équivalent ; utiliser un `Server` bas-niveau avec `@srv.list_prompts()` + `@srv.get_prompt()`). Adapter le helper `_fake_backend` ou en créer un `_fake_backend_with_prompt`. Tests :

```python
async def test_build_prompt_descriptors(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_prompt(db_conn)  # backend b1 ns=rag, grant ak1, prompt "welcome"
    prompts = await build_prompt_descriptors(db_conn, apikey_id="ak1", owner_login="alice")
    assert any(p.name == "rag__welcome" for p in prompts)


async def test_execute_prompt_get_routes(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_prompt(db_conn)
    result = await execute_prompt_get(
        db_conn, apikey_id="ak1", owner_login="alice",
        name="rag__welcome", arguments={"who": "Bob"},
        open_session_fn=_patched_open_session(_fake_backend_with_prompt()),
    )
    assert "Bob" in result.messages[0].content.text
    audit = await list_for_owner(db_conn, "alice")
    assert audit[0]["status"] == "ok" and audit[0]["namespaced_name"] == "rag__welcome"


async def test_execute_prompt_get_denied(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_prompt(db_conn)
    with pytest.raises(McpError) as exc:
        await execute_prompt_get(
            db_conn, apikey_id="ak1", owner_login="alice",
            name="rag__ghost", arguments=None,
            open_session_fn=_patched_open_session(_fake_backend_with_prompt()),
        )
    assert exc.value.error.code == METHOD_NOT_FOUND
    audit = await list_for_owner(db_conn, "alice")
    assert audit[0]["status"] == "denied"
```

> Note implémenteur : créer `_seed_backend_with_prompt` (insère backend b1 ns=rag, grant, et `upsert_primitive(kind="prompt", original_name="welcome", definition={"name":"welcome","description":"..."})`) et `_fake_backend_with_prompt` (un `Server` bas-niveau avec `@srv.list_prompts()` renvoyant `[types.Prompt(name="welcome", ...)]` et `@srv.get_prompt()` renvoyant un `types.GetPromptResult(messages=[types.PromptMessage(role="user", content=types.TextContent(type="text", text=f"Welcome {arguments['who']}"))])`). Vérifier la forme exacte de `PromptMessage`/`GetPromptResult` dans `mcp.types`.

- [ ] **Step 2: Lancer le test (rouge)**

Run: `cd /d/srcs/devpod-ui/backend && uv run pytest tests/mcp/test_server.py -v`
Expected : échec d'import (`cannot import name 'build_prompt_descriptors'`).

- [ ] **Step 3: Implémenter**

Dans `backend/src/portal/mcp/server.py`, ajouter `from portal.mcp.client import get_backend_prompt` (et garder les imports existants). Puis :

```python
async def build_prompt_descriptors(
    conn: AsyncConnection, *, apikey_id: str, owner_login: str
) -> list[types.Prompt]:
    prims = await aggregate_primitives(
        conn, apikey_id=apikey_id, owner_login=owner_login, kind="prompt"
    )
    return [
        types.Prompt(
            name=p.namespaced_name,
            description=p.definition.get("description"),
            arguments=p.definition.get("arguments"),
        )
        for p in prims
    ]


async def execute_prompt_get(
    conn: AsyncConnection, *, apikey_id: str, owner_login: str,
    name: str, arguments: dict[str, str] | None,
    open_session_fn: Any = open_session,
) -> types.GetPromptResult:
    target = await resolve_call(
        conn, apikey_id=apikey_id, owner_login=owner_login, namespaced_name=name, kind="prompt"
    )
    if target is None:
        await audit_record(conn, apikey_id=apikey_id, owner_login=owner_login,
                           namespaced_name=name, backend_id=None, backend_key_id=None,
                           latency_ms=None, status="denied", error=None)
        raise McpError(ErrorData(code=METHOD_NOT_FOUND, message="unknown prompt"))
    bearer = await _resolve_bearer(conn, target, name=name, apikey_id=apikey_id, owner_login=owner_login)
    started = time.perf_counter()
    try:
        async with open_session_fn(target.url, bearer=bearer) as session:
            result = await get_backend_prompt(session, target.original_name, arguments)
    except BackendUnavailable as exc:
        await audit_record(conn, apikey_id=apikey_id, owner_login=owner_login,
                           namespaced_name=name, backend_id=target.backend_id,
                           backend_key_id=target.backend_key_id, latency_ms=None,
                           status="timeout", error=str(exc))
        raise McpError(ErrorData(code=INTERNAL_ERROR,
                                 message=f"backend unavailable: {target.backend_id}")) from exc
    await audit_record(conn, apikey_id=apikey_id, owner_login=owner_login,
                       namespaced_name=name, backend_id=target.backend_id,
                       backend_key_id=target.backend_key_id,
                       latency_ms=int((time.perf_counter() - started) * 1000),
                       status="ok", error=None)
    return result
```

Et **extraire** la résolution de clé+audit-erreur en helper réutilisable `_resolve_bearer` (utilisé aussi par `execute_tool_call` — refactor optionnel mais propre ; sinon dupliquer inline). Si extraction : 

```python
async def _resolve_bearer(
    conn: AsyncConnection, target: CallTarget, *,
    name: str, apikey_id: str, owner_login: str,
) -> str | None:
    key_row = (
        await get_backend_key_secret(conn, target.backend_id, target.backend_key_id)
        if target.backend_key_id else None
    )
    try:
        secret = await resolve_grant_key(key_row)
    except UnresolvableSecret as exc:
        await audit_record(conn, apikey_id=apikey_id, owner_login=owner_login,
                           namespaced_name=name, backend_id=target.backend_id,
                           backend_key_id=target.backend_key_id, latency_ms=None,
                           status="error", error="key not resolvable")
        raise McpError(ErrorData(code=INTERNAL_ERROR,
                                 message="outbound key not resolvable at runtime")) from exc
    return secret.reveal() if secret else None
```

(Importer `CallTarget` depuis `portal.mcp.aggregator` si pas déjà fait. Si tu refactores `execute_tool_call` pour utiliser `_resolve_bearer`, garde son comportement identique et ne casse aucun test Plan 4.)

- [ ] **Step 4: Vert + lint**

Run: `cd /d/srcs/devpod-ui/backend && uv run pytest tests/mcp/test_server.py -v` → tests purs PASS ; nouveaux tests DB SKIPPED ; aucun test Plan 4 cassé.
Run: `cd /d/srcs/devpod-ui/backend && uv run ruff check src/portal/mcp/server.py tests/mcp/test_server.py && uv run mypy src/portal/mcp/server.py` → propre.

- [ ] **Step 5: Commit**

```bash
cd /d/srcs/devpod-ui && git add backend/src/portal/mcp/server.py backend/tests/mcp/test_server.py
git commit -m "feat(mcp): serveur frontal — prompts (list_prompts + get_prompt + audit)"
```

---

### Task 4 : Serveur — resources (`list_resources` + `read_resource` + audit)

**Files:**
- Modify: `backend/src/portal/mcp/server.py`
- Test: `backend/tests/mcp/test_server.py`

**Interfaces:**
- Produces:
  - `async build_resource_descriptors(conn, *, apikey_id, owner_login) -> list[types.Resource]` — agrège kind="resource", `uri = make_namespaced_uri(p.namespace, p.original_name)`.
  - `async execute_resource_read(conn, *, apikey_id, owner_login, namespaced_uri: str, open_session_fn=open_session) -> list[ReadResourceContents]` — `resolve_resource` → None → audit denied + `McpError(METHOD_NOT_FOUND, "unknown resource")` ; clé via `_resolve_bearer` ; `open_session` → `BackendUnavailable` → audit timeout + INTERNAL_ERROR ; `read_backend_resource(session, AnyUrl(original))` → convertit chaque `contents[]` en `ReadResourceContents(content, mime_type)` → audit ok.

- [ ] **Step 1: Écrire le test rouge**

Ajouter à `backend/tests/mcp/test_server.py` (imports : `build_resource_descriptors, execute_resource_read` ; `from mcp.server.lowlevel.helper_types import ReadResourceContents` ; `make_namespaced_uri` depuis aggregator) :

```python
async def test_build_resource_descriptors_namespaces_uri(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_resource(db_conn)  # resource original_name="resource://foo"
    resources = await build_resource_descriptors(db_conn, apikey_id="ak1", owner_login="alice")
    uris = {str(r.uri) for r in resources}
    assert make_namespaced_uri("rag", "resource://foo") in uris


async def test_execute_resource_read_routes(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_resource(db_conn)
    namespaced = make_namespaced_uri("rag", "resource://foo")
    contents = await execute_resource_read(
        db_conn, apikey_id="ak1", owner_login="alice", namespaced_uri=namespaced,
        open_session_fn=_patched_open_session(_fake_backend_with_resource()),
    )
    assert contents[0].content == "hello"
    audit = await list_for_owner(db_conn, "alice")
    assert audit[0]["status"] == "ok" and audit[0]["namespaced_name"] == namespaced


async def test_execute_resource_read_denied(db_conn: AsyncConnection) -> None:
    await _seed_apikey(db_conn, "mcpk_secret")
    await _seed_backend_with_resource(db_conn)
    with pytest.raises(McpError) as exc:
        await execute_resource_read(
            db_conn, apikey_id="ak1", owner_login="alice",
            namespaced_uri=make_namespaced_uri("rag", "resource://ghost"),
            open_session_fn=_patched_open_session(_fake_backend_with_resource()),
        )
    assert exc.value.error.code == METHOD_NOT_FOUND
    assert (await list_for_owner(db_conn, "alice"))[0]["status"] == "denied"
```

> Note implémenteur : `_seed_backend_with_resource` insère un backend b1 ns=rag, grant ak1, et `upsert_primitive(kind="resource", original_name="resource://foo", definition={"uri":"resource://foo","name":"Foo"})`. `_fake_backend_with_resource` = `Server` bas-niveau avec `@srv.list_resources()` → `[types.Resource(uri=AnyUrl("resource://foo"), name="Foo")]` et `@srv.read_resource()` → `[ReadResourceContents(content="hello", mime_type="text/plain")]`. Vérifier les types réels.

- [ ] **Step 2: Lancer le test (rouge)**

Run: `cd /d/srcs/devpod-ui/backend && uv run pytest tests/mcp/test_server.py -v`
Expected : échec d'import (`cannot import name 'build_resource_descriptors'`).

- [ ] **Step 3: Implémenter**

Dans `backend/src/portal/mcp/server.py`, ajouter imports : `import base64`, `from pydantic import AnyUrl, TypeAdapter`, `from mcp.server.lowlevel.helper_types import ReadResourceContents`, `from portal.mcp.aggregator import make_namespaced_uri, resolve_resource`, `from portal.mcp.client import read_backend_resource`. Puis :

```python
_ANYURL = TypeAdapter(AnyUrl)


async def build_resource_descriptors(
    conn: AsyncConnection, *, apikey_id: str, owner_login: str
) -> list[types.Resource]:
    prims = await aggregate_primitives(
        conn, apikey_id=apikey_id, owner_login=owner_login, kind="resource"
    )
    return [
        types.Resource(
            uri=_ANYURL.validate_python(make_namespaced_uri(p.namespace, p.original_name)),
            name=p.definition.get("name") or p.original_name,
            description=p.definition.get("description"),
            mimeType=p.definition.get("mimeType"),
        )
        for p in prims
    ]


def _to_read_contents(result: ReadResourceResult) -> list[ReadResourceContents]:
    out: list[ReadResourceContents] = []
    for c in result.contents:
        if isinstance(c, types.TextResourceContents):
            out.append(ReadResourceContents(content=c.text, mime_type=c.mimeType))
        elif isinstance(c, types.BlobResourceContents):
            out.append(ReadResourceContents(content=base64.b64decode(c.blob), mime_type=c.mimeType))
    return out


async def execute_resource_read(
    conn: AsyncConnection, *, apikey_id: str, owner_login: str,
    namespaced_uri: str, open_session_fn: Any = open_session,
) -> list[ReadResourceContents]:
    target = await resolve_resource(
        conn, apikey_id=apikey_id, owner_login=owner_login, namespaced_uri=namespaced_uri
    )
    if target is None:
        await audit_record(conn, apikey_id=apikey_id, owner_login=owner_login,
                           namespaced_name=namespaced_uri, backend_id=None, backend_key_id=None,
                           latency_ms=None, status="denied", error=None)
        raise McpError(ErrorData(code=METHOD_NOT_FOUND, message="unknown resource"))
    bearer = await _resolve_bearer(conn, target, name=namespaced_uri,
                                   apikey_id=apikey_id, owner_login=owner_login)
    started = time.perf_counter()
    try:
        async with open_session_fn(target.url, bearer=bearer) as session:
            result = await read_backend_resource(session, _ANYURL.validate_python(target.original_name))
    except BackendUnavailable as exc:
        await audit_record(conn, apikey_id=apikey_id, owner_login=owner_login,
                           namespaced_name=namespaced_uri, backend_id=target.backend_id,
                           backend_key_id=target.backend_key_id, latency_ms=None,
                           status="timeout", error=str(exc))
        raise McpError(ErrorData(code=INTERNAL_ERROR,
                                 message=f"backend unavailable: {target.backend_id}")) from exc
    await audit_record(conn, apikey_id=apikey_id, owner_login=owner_login,
                       namespaced_name=namespaced_uri, backend_id=target.backend_id,
                       backend_key_id=target.backend_key_id,
                       latency_ms=int((time.perf_counter() - started) * 1000),
                       status="ok", error=None)
    return _to_read_contents(result)
```

> Note : `ReadResourceResult` doit être importé dans `server.py` (`from mcp.types import ..., ReadResourceResult`). Le SDK assignera l'URI **namespacée** (celle de la requête) aux contents renvoyés — les URIs internes par-content du backend ne sont pas préservées (limite SDK acceptée : le handler `read_resource` ne renvoie que `content`+`mime_type`). Le documenter dans le rapport.

- [ ] **Step 4: Vert + lint**

Run: `cd /d/srcs/devpod-ui/backend && uv run pytest tests/mcp/test_server.py -v` → tests purs PASS ; nouveaux DB SKIPPED ; rien de cassé.
Run: `cd /d/srcs/devpod-ui/backend && uv run ruff check src/portal/mcp/server.py tests/mcp/test_server.py && uv run mypy src/portal/mcp/server.py` → propre. Si `server.py` > 300 lignes, le signaler (DONE_WITH_CONCERNS) — un split éventuel (`server_handlers.py`) serait décidé hors tâche.

- [ ] **Step 5: Commit**

```bash
cd /d/srcs/devpod-ui && git add backend/src/portal/mcp/server.py backend/tests/mcp/test_server.py
git commit -m "feat(mcp): serveur frontal — resources (list_resources + read_resource + audit)"
```

---

### Task 5 : Enregistrement des handlers dans `build_server` + smoke ASGI

**Files:**
- Modify: `backend/src/portal/mcp/server.py` (handlers dans `build_server`)
- Test: `backend/tests/mcp/test_server_asgi.py`

**Interfaces:**
- Produces : `build_server` enregistre 4 handlers supplémentaires : `@server.list_resources()`, `@server.read_resource()`, `@server.list_prompts()`, `@server.get_prompt()` — auth Bearer + conn `connect()` (list_* lecture seule sans commit ; read_resource/get_prompt avec commit-on-except pour audit durable), délégation aux fonctions des Tasks 3-4.

- [ ] **Step 1: Implémenter les handlers**

Dans `build_server` (`backend/src/portal/mcp/server.py`), ajouter après les handlers tools (mêmes `type: ignore` étroits que les décorateurs existants ; lire les codes exacts attendus par mypy) :

```python
    @server.list_resources()  # type: ignore[no-untyped-call,untyped-decorator]
    async def _list_resources() -> list[types.Resource]:
        req = server.request_context.request
        token = extract_bearer(req.headers if req is not None else {})
        async with _get_engine().connect() as conn:
            tenant = await resolve_tenant(conn, token)
            if tenant is None:
                raise McpError(_UNAUTHORIZED)
            return await build_resource_descriptors(
                conn, apikey_id=str(tenant["id"]), owner_login=str(tenant["owner_login"])
            )

    @server.read_resource()  # type: ignore[no-untyped-call,untyped-decorator]
    async def _read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
        req = server.request_context.request
        token = extract_bearer(req.headers if req is not None else {})
        async with _get_engine().connect() as conn:
            tenant = await resolve_tenant(conn, token)
            if tenant is None:
                raise McpError(_UNAUTHORIZED)
            try:
                contents = await execute_resource_read(
                    conn, apikey_id=str(tenant["id"]), owner_login=str(tenant["owner_login"]),
                    namespaced_uri=str(uri),
                )
            except McpError:
                await conn.commit()
                raise
            await conn.commit()
            return contents

    @server.list_prompts()  # type: ignore[no-untyped-call,untyped-decorator]
    async def _list_prompts() -> list[types.Prompt]:
        req = server.request_context.request
        token = extract_bearer(req.headers if req is not None else {})
        async with _get_engine().connect() as conn:
            tenant = await resolve_tenant(conn, token)
            if tenant is None:
                raise McpError(_UNAUTHORIZED)
            return await build_prompt_descriptors(
                conn, apikey_id=str(tenant["id"]), owner_login=str(tenant["owner_login"])
            )

    @server.get_prompt()  # type: ignore[no-untyped-call,untyped-decorator]
    async def _get_prompt(name: str, arguments: dict[str, str] | None) -> types.GetPromptResult:
        req = server.request_context.request
        token = extract_bearer(req.headers if req is not None else {})
        async with _get_engine().connect() as conn:
            tenant = await resolve_tenant(conn, token)
            if tenant is None:
                raise McpError(_UNAUTHORIZED)
            try:
                result = await execute_prompt_get(
                    conn, apikey_id=str(tenant["id"]), owner_login=str(tenant["owner_login"]),
                    name=name, arguments=arguments,
                )
            except McpError:
                await conn.commit()
                raise
            await conn.commit()
            return result
```

- [ ] **Step 2: Écrire le smoke ASGI (rouge — DB-only)**

Ajouter à `backend/tests/mcp/test_server_asgi.py` un test qui, via le client MCP in-process (réutiliser le helper existant `_build_app`/transport + `/mcp/` + `follow_redirects=True`), avec un Bearer valide et un backend seedé (prompt + resource au catalogue), vérifie : `session.list_prompts()` contient `rag__welcome` ET `session.list_resources()` contient l'URI namespacée. (Le routage `read_resource`/`get_prompt` réel nécessiterait un vrai backend joignable ; le smoke se limite au listing agrégé via la DB, comme le smoke tools.)

```python
async def test_mcp_endpoint_lists_resources_and_prompts(db_engine) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4())))
        await insert_apikey(conn, id="ak1", owner_login="alice",
                            token_hash=token_hash("mcpk_secret"), label="")
        await conn.execute(insert(mcp_backend).values(
            id="b1", owner_login="alice", namespace="rag", name="RAG",
            url="https://rag/mcp", transport="streamable_http"))
        await set_grant(conn, apikey_id="ak1", backend_id="b1", backend_key_id=None)
        await upsert_primitive(conn, backend_id="b1", kind="prompt", original_name="welcome",
                               definition={"name": "welcome"}, definition_hash="p1")
        await upsert_primitive(conn, backend_id="b1", kind="resource", original_name="resource://foo",
                               definition={"uri": "resource://foo", "name": "Foo"}, definition_hash="r1")
    # ... monter l'app + LifespanManager + client MCP (cf. test existant) ...
    # async with ClientSession(...) as session:
    #     await session.initialize()
    #     prompts = await session.list_prompts()
    #     assert any(p.name == "rag__welcome" for p in prompts.prompts)
    #     resources = await session.list_resources()
    #     assert any(str(r.uri).startswith("gw+rag") for r in resources.resources)
```

> Note implémenteur : compléter le corps en réutilisant EXACTEMENT le montage du test `test_mcp_endpoint_lists_native_tool_with_valid_bearer` (même `_build_app`, transport ASGI, `streamable_http_client("http://test/mcp/", http_client=...)`, `follow_redirects=True`). Importer `mcp_backend`, `set_grant`, `upsert_primitive`.

- [ ] **Step 3: Lancer (local : skip ; lint)**

Run: `cd /d/srcs/devpod-ui/backend && uv run pytest tests/mcp -q` → tests purs PASS, tous les DB/ASGI SKIPPED, 0 warning, 0 erreur de collection.
Run: `cd /d/srcs/devpod-ui/backend && uv run ruff check src/portal/mcp/server.py tests/mcp/test_server_asgi.py && uv run mypy src/portal/mcp/server.py` → propre.

- [ ] **Step 4: Commit**

```bash
cd /d/srcs/devpod-ui && git add backend/src/portal/mcp/server.py backend/tests/mcp/test_server_asgi.py
git commit -m "feat(mcp): handlers frontaux resources/prompts montés + smoke ASGI listing"
```

---

## Validation finale du plan

- [ ] `cd /d/srcs/devpod-ui/backend && uv run ruff check src/portal/mcp tests/mcp` → propre.
- [ ] `cd /d/srcs/devpod-ui/backend && uv run mypy src/portal/mcp` → propre.
- [ ] `cd /d/srcs/devpod-ui/backend && uv run pytest tests/mcp -q` → tests purs/in-memory verts, DB/ASGI skipped, 0 warning.
- [ ] Push → **CI Docker** : exécution réelle (client read/get, namespacing URI round-trip, build_*_descriptors, execute_prompt_get/resource_read routage+erreurs+audit, smoke ASGI resources/prompts). Tout vert.
- [ ] Mettre à jour `.superpowers/sdd/progress-runtime.md` (journal Plan 5).

## Couverture spec (auto-review)

- §3/§9.3 resources/list+read & prompts/list+get fédérés, namespacés, routés : Tasks 3-5.
- Namespacing URI réversible (scheme `gw+ns`) : Task 2 (`make/split_namespaced_uri`).
- §6 résolution clé sortante réutilisée (`_resolve_bearer`) ; §13 mapping erreurs (denied/timeout/error) + messages génériques : Tasks 3-4.
- Audit exhaustif sur read_resource/get_prompt (durable via commit-on-except) : Tasks 3-5.
- §10 deny-by-default sans fuite : `resolve_call`/`resolve_resource` → None → METHOD_NOT_FOUND générique.
- **Hors de ce lot** (roadmap) : notifications `list_changed` + health/résilience/refresh TTL (Plan 6) ; UI curation par grant (Plan 7). Limite SDK notée : `read_resource` ne préserve pas les URIs par-content du backend (le SDK assigne l'URI de requête).
