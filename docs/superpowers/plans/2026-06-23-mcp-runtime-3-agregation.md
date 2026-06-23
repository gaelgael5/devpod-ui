# MCP Runtime — Plan 3 : Agrégation & résolution clé sortante — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Calculer, pour une apikey donnée, la vue agrégée des primitives MCP autorisées (catalogue → curation → namespacing → exclusion quarantine) et résoudre le routage d'un appel namespacé vers son backend + sa clé sortante.

**Architecture:** Module pur `portal/mcp/aggregator.py` qui lit le registre (grants, backends) et le catalogue (`mcp_tool_catalog`) déjà peuplé par le Plan 2, applique la curation par grant (`expose_mode`/`expose`), préfixe par `<namespace>__`, exclut les primitives quarantined, et expose deux fonctions : `aggregate_primitives` (vue liste) et `resolve_call` (routage d'un appel). Plus une fonction DB `get_backend_key_secret` qui récupère le blob chiffré d'une clé de service (réservé au runtime, jamais exposé par un listing). Aucune connexion réseau ici : tout est testable en DB (testcontainers / CI Docker).

**Tech Stack:** Python 3.12, SQLAlchemy Core async (asyncpg), pydantic v2, pytest + pytest-asyncio. Tests DB via fixture `db_conn` (PostgreSQL testcontainers, skip si Docker absent en local → validés sur CI Docker `test.yml`).

## Global Constraints

- `from __future__ import annotations` en tête de chaque fichier.
- pydantic v2 ; modèles internes immuables via `model_config = ConfigDict(frozen=True)`.
- SQLAlchemy Core async uniquement ; aucune I/O bloquante.
- Fichiers ≤ 300 lignes ; logs structlog sans secret (aucun log de secret ici).
- Branche `dev` ; commits conventionnels FR.
- TDD strict : test rouge → impl → test vert → commit, par étape.
- Tests DB skippent en local (Docker absent) et sont la cible de validation CI Docker.
- Découpe namespacé **sur le PREMIER `__`** (séparateur `NS_SEP = "__"`).
- Deny-by-default : `resolve_call` renvoie `None` sans révéler l'existence d'un backend quand l'appel n'est pas autorisé.
- Hygiène secret : `get_backend_key_secret` est le SEUL accès au blob `secret_value_local` ; ne JAMAIS l'ajouter aux listings (`get_backend_key`/`list_backend_keys`).

---

## Surface existante (Plans 1 & 2) — consommée par ce plan

**Interfaces consommées (signatures exactes) :**
- `portal.db.mcp.list_grants(conn, apikey_id) -> list[dict]` — colonnes : `apikey_id, backend_id, backend_key_id, expose_mode, expose`.
- `portal.db.mcp.get_backend(conn, owner_login, backend_id) -> dict | None` — colonnes : `id, owner_login, namespace, name, url, transport, enabled, created_at, updated_at`.
- `portal.db.mcp_catalog.list_primitives(conn, backend_id, kind) -> list[dict]` — colonnes : `backend_id, kind, original_name, definition, definition_hash, first_seen, last_seen, quarantined`.
- Table `portal.db.tables.mcp_backend_key` — colonnes : `id, backend_id, slug, description, storage_type, secret_value_local (LargeBinary, NULL), secret_value_vault_ref (Text, NULL), vault_identifier, enabled, created_at`.
- `portal.db.mcp.insert_backend_key(conn, *, id, backend_id, slug, description, storage_type, secret_value_local, secret_value_vault_ref, vault_identifier) -> None` — pour seeding test.
- `portal.db.mcp.set_grant(conn, *, apikey_id, backend_id, backend_key_id, expose_mode="all", expose=None) -> None` — pour seeding test.
- `portal.db.mcp_catalog.upsert_primitive(conn, *, backend_id, kind, original_name, definition, definition_hash) -> bool` — pour seeding test.
- `portal.mcp.runtime_secrets.resolve_grant_key(key_row: dict | None) -> Secret | None` — consommera le dict renvoyé par `get_backend_key_secret` (clés attendues : `storage_type, secret_value_local, secret_value_vault_ref`). **Pas appelée dans ce plan** ; le contrat de forme est vérifié par le test de `get_backend_key_secret`.
- Fixture test `db_conn: AsyncConnection` (tests/conftest.py) — transaction rollbackée, schéma via `metadata.create_all`.
- Tables `portal.db.tables.users`, `mcp_backend`, `mcp_apikey` pour seeding.

---

### Task 1 : `get_backend_key_secret` (accès runtime au blob chiffré)

**Files:**
- Modify: `backend/src/portal/db/mcp.py` (ajout d'une fonction)
- Test: `backend/tests/db/test_mcp.py` (créer si absent ; sinon ajouter le test)

**Interfaces:**
- Consumes: table `mcp_backend_key` ; `insert_backend_key` (seeding).
- Produces: `get_backend_key_secret(conn: AsyncConnection, backend_id: str, key_id: str) -> dict[str, Any] | None` — renvoie `{"storage_type", "secret_value_local", "secret_value_vault_ref"}` ou `None`. Forme directement consommable par `resolve_grant_key` (Plan 4).

- [ ] **Step 1: Écrire le test rouge**

Vérifier d'abord si `backend/tests/db/test_mcp.py` existe. S'il existe, ajouter la fonction de test ci-dessous (et les imports manquants en tête). S'il n'existe pas, créer le fichier avec ce contenu complet :

```python
from __future__ import annotations

import uuid

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import get_backend_key, get_backend_key_secret, insert_backend_key
from portal.db.tables import mcp_backend, users


async def _seed_backend(conn: AsyncConnection) -> None:
    await conn.execute(
        insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
    )
    await conn.execute(
        insert(mcp_backend).values(
            id="b1", owner_login="alice", namespace="rag", name="RAG",
            url="https://rag/mcp", transport="streamable_http",
        )
    )


async def test_get_backend_key_secret_returns_blob(db_conn: AsyncConnection) -> None:
    await _seed_backend(db_conn)
    await insert_backend_key(
        db_conn,
        id="k1", backend_id="b1", slug="prod", description="",
        storage_type="local", secret_value_local=b"\x01\x02\x03",
        secret_value_vault_ref=None, vault_identifier=None,
    )

    row = await get_backend_key_secret(db_conn, "b1", "k1")
    assert row is not None
    assert row["storage_type"] == "local"
    assert row["secret_value_local"] == b"\x01\x02\x03"
    assert row["secret_value_vault_ref"] is None

    # Hygiène : le listing NE doit PAS exposer le blob.
    listed = await get_backend_key(db_conn, "b1", "k1")
    assert listed is not None
    assert "secret_value_local" not in listed


async def test_get_backend_key_secret_unknown_returns_none(db_conn: AsyncConnection) -> None:
    await _seed_backend(db_conn)
    assert await get_backend_key_secret(db_conn, "b1", "nope") is None
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd backend && uv run pytest tests/db/test_mcp.py -v`
Expected (local, Docker absent) : SKIP des tests DB **mais** échec à l'import : `ImportError: cannot import name 'get_backend_key_secret'`. Si l'import casse la collection, c'est le rouge attendu.

- [ ] **Step 3: Implémenter `get_backend_key_secret`**

Dans `backend/src/portal/db/mcp.py`, à proximité de `get_backend_key`, ajouter (vérifier que `select` et `mcp_backend_key` sont déjà importés en tête — ils le sont pour les autres fonctions clés) :

```python
async def get_backend_key_secret(
    conn: AsyncConnection, backend_id: str, key_id: str
) -> dict[str, Any] | None:
    """Récupère le secret chiffré d'une clé de service — usage RUNTIME uniquement.

    Contrairement à `get_backend_key`/`list_backend_keys`, sélectionne
    `secret_value_local` (blob chiffré KEK). Réservé à la résolution du secret
    sortant au runtime ; ne JAMAIS l'exposer dans un listing/registre.
    """
    row = (
        await conn.execute(
            select(
                mcp_backend_key.c.storage_type,
                mcp_backend_key.c.secret_value_local,
                mcp_backend_key.c.secret_value_vault_ref,
            ).where(
                mcp_backend_key.c.id == key_id,
                mcp_backend_key.c.backend_id == backend_id,
            )
        )
    ).mappings().first()
    return dict(row) if row else None
```

- [ ] **Step 4: Lancer le test pour vérifier qu'il passe (ou skippe proprement)**

Run: `cd backend && uv run pytest tests/db/test_mcp.py -v`
Expected (local) : la collection passe, tests DB **SKIPPED** (Docker absent), 0 erreur d'import.
Run: `cd backend && uv run ruff check src/portal/db/mcp.py tests/db/test_mcp.py && uv run mypy src/portal/db/mcp.py`
Expected : All checks passed / no issues.

- [ ] **Step 5: Commit**

```bash
git add backend/src/portal/db/mcp.py backend/tests/db/test_mcp.py
git commit -m "feat(mcp): get_backend_key_secret — accès runtime au blob chiffré (hors listing)"
```

---

### Task 2 : Agrégateur — modèles, découpe, curation, `aggregate_primitives`

**Files:**
- Create: `backend/src/portal/mcp/aggregator.py`
- Test: `backend/tests/mcp/test_aggregator.py`

**Interfaces:**
- Consumes: `list_grants`, `get_backend` (`portal.db.mcp`) ; `list_primitives` (`portal.db.mcp_catalog`).
- Produces:
  - `NS_SEP: str = "__"`
  - `class AggregatedPrimitive(BaseModel, frozen)` — champs : `namespaced_name: str`, `kind: str`, `backend_id: str`, `original_name: str`, `definition: dict[str, Any]`.
  - `split_namespaced(name: str) -> tuple[str, str] | None` — découpe sur le premier `__` ; `None` si pas de `__` ou préfixe vide.
  - `aggregate_primitives(conn, *, apikey_id: str, owner_login: str, kind: str) -> list[AggregatedPrimitive]`.

- [ ] **Step 1: Écrire le test rouge (découpe pure + agrégation DB)**

Créer `backend/tests/mcp/test_aggregator.py` :

```python
from __future__ import annotations

import uuid

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import insert_apikey, insert_backend_key, set_grant
from portal.db.mcp_catalog import upsert_primitive
from portal.db.tables import mcp_backend, users
from portal.mcp.aggregator import (
    AggregatedPrimitive,
    aggregate_primitives,
    split_namespaced,
)


def test_split_namespaced_first_separator() -> None:
    assert split_namespaced("rag__search") == ("rag", "search")
    # découpe sur le PREMIER __ ; l'original peut en contenir d'autres
    assert split_namespaced("rag__a__b") == ("rag", "a__b")


def test_split_namespaced_invalid() -> None:
    assert split_namespaced("nosep") is None
    assert split_namespaced("__leading") is None


async def _seed(conn: AsyncConnection, *, enabled: bool = True) -> None:
    await conn.execute(
        insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4()))
    )
    await conn.execute(
        insert(mcp_backend).values(
            id="b1", owner_login="alice", namespace="rag", name="RAG",
            url="https://rag/mcp", transport="streamable_http", enabled=enabled,
        )
    )
    await insert_apikey(conn, id="ak1", owner_login="alice", token_hash="h", label="")


async def test_aggregate_namespaces_and_excludes_quarantined(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await set_grant(db_conn, apikey_id="ak1", backend_id="b1", backend_key_id=None)
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
        original_name="search", definition={"name": "search"},
    )


async def test_aggregate_allowlist_and_denylist(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    for name in ("a", "b", "c"):
        await upsert_primitive(
            db_conn, backend_id="b1", kind="tool", original_name=name,
            definition={"name": name}, definition_hash=name,
        )

    await set_grant(
        db_conn, apikey_id="ak1", backend_id="b1", backend_key_id=None,
        expose_mode="allowlist", expose=["a", "c"],
    )
    allow = await aggregate_primitives(db_conn, apikey_id="ak1", owner_login="alice", kind="tool")
    assert {p.original_name for p in allow} == {"a", "c"}

    await set_grant(
        db_conn, apikey_id="ak1", backend_id="b1", backend_key_id=None,
        expose_mode="denylist", expose=["b"],
    )
    deny = await aggregate_primitives(db_conn, apikey_id="ak1", owner_login="alice", kind="tool")
    assert {p.original_name for p in deny} == {"a", "c"}


async def test_aggregate_skips_disabled_backend(db_conn: AsyncConnection) -> None:
    await _seed(db_conn, enabled=False)
    await set_grant(db_conn, apikey_id="ak1", backend_id="b1", backend_key_id=None)
    await upsert_primitive(
        db_conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "search"}, definition_hash="h1",
    )
    prims = await aggregate_primitives(db_conn, apikey_id="ak1", owner_login="alice", kind="tool")
    assert prims == []
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd backend && uv run pytest tests/mcp/test_aggregator.py -v`
Expected : échec d'import (`cannot import name 'aggregate_primitives'`). Les deux tests `split_*` (purs) doivent aussi échouer à la collection pour la même raison.

- [ ] **Step 3: Implémenter l'agrégateur (modèles + découpe + curation + agrégation)**

Créer `backend/src/portal/mcp/aggregator.py` :

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import get_backend, list_grants
from portal.db.mcp_catalog import list_primitives

NS_SEP = "__"


class AggregatedPrimitive(BaseModel):
    """Primitive d'un backend, préfixée et prête à exposer côté frontal."""

    model_config = ConfigDict(frozen=True)

    namespaced_name: str
    kind: str
    backend_id: str
    original_name: str
    definition: dict[str, Any]


def split_namespaced(name: str) -> tuple[str, str] | None:
    """Découpe `<namespace>__<original>` sur le PREMIER `__`.

    Renvoie `None` si aucun `__` ou si le préfixe namespace est vide.
    """
    idx = name.find(NS_SEP)
    if idx <= 0:
        return None
    return name[:idx], name[idx + len(NS_SEP) :]


def _curation_allows(expose_mode: str, expose: list[str], original_name: str) -> bool:
    if expose_mode == "allowlist":
        return original_name in expose
    if expose_mode == "denylist":
        return original_name not in expose
    return True  # "all"


async def aggregate_primitives(
    conn: AsyncConnection, *, apikey_id: str, owner_login: str, kind: str
) -> list[AggregatedPrimitive]:
    """Vue agrégée des primitives `kind` autorisées pour cette apikey.

    grants → backends enabled & possédés → catalogue → curation → namespacing,
    en excluant les primitives quarantined.
    """
    out: list[AggregatedPrimitive] = []
    for grant in await list_grants(conn, apikey_id):
        backend = await get_backend(conn, owner_login, grant["backend_id"])
        if backend is None or not backend["enabled"]:
            continue
        namespace = backend["namespace"]
        expose = grant["expose"] or []
        for prim in await list_primitives(conn, grant["backend_id"], kind):
            if prim["quarantined"]:
                continue
            if not _curation_allows(grant["expose_mode"], expose, prim["original_name"]):
                continue
            out.append(
                AggregatedPrimitive(
                    namespaced_name=f"{namespace}{NS_SEP}{prim['original_name']}",
                    kind=kind,
                    backend_id=grant["backend_id"],
                    original_name=prim["original_name"],
                    definition=prim["definition"],
                )
            )
    return out
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent (purs) / skippent (DB)**

Run: `cd backend && uv run pytest tests/mcp/test_aggregator.py -v`
Expected (local) : `test_split_namespaced_first_separator` et `test_split_namespaced_invalid` **PASSED** ; les trois tests DB **SKIPPED** (Docker absent).
Run: `cd backend && uv run ruff check src/portal/mcp/aggregator.py tests/mcp/test_aggregator.py && uv run mypy src/portal/mcp/aggregator.py`
Expected : propre.

- [ ] **Step 5: Commit**

```bash
git add backend/src/portal/mcp/aggregator.py backend/tests/mcp/test_aggregator.py
git commit -m "feat(mcp): agrégation des primitives (curation + namespacing + exclusion quarantine)"
```

---

### Task 3 : `resolve_call` — routage d'un appel namespacé (deny-by-default)

**Files:**
- Modify: `backend/src/portal/mcp/aggregator.py` (ajout `CallTarget` + `resolve_call`)
- Test: `backend/tests/mcp/test_aggregator.py` (ajout des cas de routage)

**Interfaces:**
- Consumes: `split_namespaced`, `_curation_allows`, `list_grants`, `get_backend`, `list_primitives`.
- Produces:
  - `class CallTarget(BaseModel, frozen)` — champs : `backend_id: str`, `original_name: str`, `url: str`, `transport: str`, `backend_key_id: str | None`.
  - `resolve_call(conn, *, apikey_id: str, owner_login: str, namespaced_name: str, kind: str) -> CallTarget | None` — `None` si non autorisé/inconnu/quarantined (sans révéler l'existence). Consommé par le serveur frontal (Plan 4) pour ouvrir la session backend et résoudre la clé.

- [ ] **Step 1: Écrire le test rouge**

Ajouter à `backend/tests/mcp/test_aggregator.py` (imports : compléter la ligne d'import depuis `portal.mcp.aggregator` avec `CallTarget` et `resolve_call`) :

```python
from portal.mcp.aggregator import CallTarget, resolve_call  # noqa: E402 (ajouter au bloc d'import existant)


async def test_resolve_call_routes_to_backend(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await insert_backend_key(
        db_conn, id="k1", backend_id="b1", slug="prod", description="",
        storage_type="local", secret_value_local=b"x",
        secret_value_vault_ref=None, vault_identifier=None,
    )
    await set_grant(db_conn, apikey_id="ak1", backend_id="b1", backend_key_id="k1")
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


async def test_resolve_call_unknown_or_malformed_returns_none(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await set_grant(db_conn, apikey_id="ak1", backend_id="b1", backend_key_id=None)
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


async def test_resolve_call_curation_denied_returns_none(db_conn: AsyncConnection) -> None:
    await _seed(db_conn)
    await set_grant(
        db_conn, apikey_id="ak1", backend_id="b1", backend_key_id=None,
        expose_mode="denylist", expose=["search"],
    )
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
    await set_grant(db_conn, apikey_id="ak1", backend_id="b1", backend_key_id=None)
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
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd backend && uv run pytest tests/mcp/test_aggregator.py -v`
Expected : échec d'import (`cannot import name 'CallTarget'`).

- [ ] **Step 3: Implémenter `CallTarget` + `resolve_call`**

Dans `backend/src/portal/mcp/aggregator.py`, ajouter le modèle après `AggregatedPrimitive` :

```python
class CallTarget(BaseModel):
    """Routage résolu d'un appel namespacé vers son backend + sa clé sortante."""

    model_config = ConfigDict(frozen=True)

    backend_id: str
    original_name: str
    url: str
    transport: str
    backend_key_id: str | None
```

…et la fonction en fin de fichier :

```python
async def resolve_call(
    conn: AsyncConnection,
    *,
    apikey_id: str,
    owner_login: str,
    namespaced_name: str,
    kind: str,
) -> CallTarget | None:
    """Résout le routage d'un appel namespacé. `None` = refusé/inconnu (deny-by-default).

    Ne révèle jamais l'existence d'un backend : tout cas non autorisé renvoie `None`.
    """
    parsed = split_namespaced(namespaced_name)
    if parsed is None:
        return None
    namespace, original = parsed
    for grant in await list_grants(conn, apikey_id):
        backend = await get_backend(conn, owner_login, grant["backend_id"])
        if backend is None or not backend["enabled"] or backend["namespace"] != namespace:
            continue
        if not _curation_allows(grant["expose_mode"], grant["expose"] or [], original):
            return None
        match = next(
            (
                p
                for p in await list_primitives(conn, grant["backend_id"], kind)
                if p["original_name"] == original
            ),
            None,
        )
        if match is None or match["quarantined"]:
            return None
        return CallTarget(
            backend_id=grant["backend_id"],
            original_name=original,
            url=backend["url"],
            transport=backend["transport"],
            backend_key_id=grant["backend_key_id"],
        )
    return None
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent (purs) / skippent (DB)**

Run: `cd backend && uv run pytest tests/mcp/test_aggregator.py -v`
Expected (local) : tests purs `split_*` **PASSED** ; tous les tests DB **SKIPPED**.
Run: `cd backend && uv run ruff check src/portal/mcp/aggregator.py tests/mcp/test_aggregator.py && uv run mypy src/portal/mcp/aggregator.py`
Expected : propre. Vérifier le compteur de lignes : `aggregator.py` doit rester ≤ 300 lignes.

- [ ] **Step 5: Commit**

```bash
git add backend/src/portal/mcp/aggregator.py backend/tests/mcp/test_aggregator.py
git commit -m "feat(mcp): resolve_call — routage namespacé deny-by-default vers backend + clé"
```

---

## Validation finale du plan (avant de déclarer le lot fini)

- [ ] `cd backend && uv run ruff check src/portal/mcp tests/mcp src/portal/db tests/db` → propre.
- [ ] `cd backend && uv run mypy src/portal/mcp/aggregator.py src/portal/db/mcp.py` → propre.
- [ ] `cd backend && uv run pytest tests/mcp tests/db -q` → en local : tests purs verts, tests DB skipped, 0 erreur d'import, 0 warning.
- [ ] Push → **CI Docker** : 1ʳᵉ exécution réelle des tests DB de ce lot (get_backend_key_secret round-trip, agrégation curation/quarantine/namespacing, resolve_call deny-by-default). Tout doit être vert.
- [ ] Mettre à jour `.superpowers/sdd/progress-runtime.md` (journal Plan 3).

## Couverture spec (auto-review)

- §6 résolution secret : `get_backend_key_secret` fournit la forme exacte attendue par `resolve_grant_key` (Task 1). La résolution réelle (KEK/none/env) est câblée au Plan 4 (serveur).
- §9.1 `tools/list` étapes 2-5 (grants → catalogue → curation → namespacing → exclusion quarantine) : `aggregate_primitives` (Task 2). Étape 6 (tools natifs `gateway__*`) → Plan 4.
- §9.2 `tools/call` étapes 1-3 (découpe premier `__` → curation/grant → refus si quarantined) : `resolve_call` (Task 3). Étapes 4-7 (résolution clé, session, forward, audit) → Plan 4.
- §13 deny-by-default sans révéler l'existence : `resolve_call` renvoie `None` (Task 3).
- §12 curation par grant (`expose_mode`/`expose`, défaut `all`) : `_curation_allows` (Task 2).
- Hors de ce lot (rappel roadmap) : serveur frontal `/mcp` + audit + montage (Plan 4), resources/prompts (Plan 5), notifications/health (Plan 6), UI curation (Plan 7).
