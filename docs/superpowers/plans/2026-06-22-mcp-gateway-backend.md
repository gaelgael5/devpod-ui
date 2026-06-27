# MCP Gateway — Lot 1 Backend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mettre en place le registre administrable de la passerelle MCP : enregistrer des backends MCP par utilisateur, leurs clés de service (1..N, stockage local chiffré ou référence wallet), et émettre des apikeys clients donnant accès à un ensemble de services avec sélection de la clé à utiliser.

**Architecture:** Module `portal/mcp/` (modèles pydantic + service métier) adossé à une couche d'accès `db/mcp.py` (SQLAlchemy Core), exposé via `routes/mcp.py` sous `/me/mcp`. Le stockage des secrets sortants reprend exactement le pattern de l'onglet Secrets (`storage_type` local/harpocrate). Une brique fondation `SecretResolver` (Protocol + `EnvSecretResolver`) est livrée pour le runtime futur. **Aucune mécanique MCP runtime dans ce lot** (pas de client MCP backend, pas de serveur frontal, pas de catalogue/audit).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy Core (asyncpg), pydantic v2, Alembic, cryptography (AES-GCM via `vault/crypto.py`), pytest + pytest-asyncio + testcontainers.

## Global Constraints

- Branche `dev` exclusivement ; commits conventionnels en français.
- pydantic v2, `extra="forbid"` sur tous les modèles de config/DTO.
- `from __future__ import annotations` en tête de chaque fichier ; type hints partout.
- Fichiers max 300 lignes ; méthodes 5-15 lignes ; classes SRP.
- Logs via `structlog.get_logger(__name__)`, jamais `print()`. **Aucun secret en clair dans un log.** Le type `Secret` (`portal/secrets/types.py`) ne se déballe que via `.reveal()`.
- Persistance : SQLAlchemy Core (le projet n'utilise pas asyncpg brut malgré la spec §14). Tables dans `db/tables.py`, migration Alembic numérotée.
- Tout secret sortant : **jamais persisté en clair**. `storage_type='local'` → chiffré AES-GCM avec la master_key de session ; `storage_type='harpocrate'` → seule une référence `${vault://...}` est stockée.
- Scope **par utilisateur** : toutes les tables portent `owner_login` (FK `users.login` ON DELETE CASCADE) ; routes sous `/me/mcp` avec `Depends(require_user)`.
- Hash des apikeys clients = **sha256** (cohérent `db/tokens.py`), pas de nouvelle dépendance.
- Validation regex stricte avant tout usage : `namespace` `^[a-z0-9_]+$` **sans** `__` ; `slug` `^[a-z0-9][a-z0-9_-]{0,62}$`.
- TDD : test rouge → impl → test vert → commit. Tests DB via fixture `db_conn` (`tests/conftest.py`), `pytestmark = pytest.mark.asyncio`.

---

## File Structure

| Fichier | Responsabilité |
|---|---|
| `backend/src/portal/db/tables.py` (modif) | Déclaration des 4 tables `mcp_*` |
| `backend/alembic/versions/017_mcp_gateway.py` (créer) | Migration des 4 tables |
| `backend/src/portal/db/mcp.py` (créer) | Accès SQLAlchemy Core : CRUD backends, keys, apikeys, grants |
| `backend/src/portal/secrets/resolver.py` (modif) | Ajout du Protocol `SecretResolver` + `EnvSecretResolver` |
| `backend/src/portal/mcp/__init__.py` (créer) | Package |
| `backend/src/portal/mcp/models.py` (créer) | DTOs pydantic v2 + validateurs |
| `backend/src/portal/mcp/service.py` (créer) | Logique métier : validation, chiffrement clés, génération apikey, garde-fous |
| `backend/src/portal/routes/mcp.py` (créer) | Routes `/me/mcp/...` |
| `backend/src/portal/app.py` (modif) | Enregistrement du routeur |
| `backend/tests/db/test_mcp.py` (créer) | Tests couche DB |
| `backend/tests/secrets/test_resolver_protocol.py` (créer) | Tests SecretResolver |
| `backend/tests/mcp/test_service.py` (créer) | Tests service |
| `backend/tests/routes/test_mcp_routes.py` (créer) | Tests d'intégration routes |

**Modèle de données :**

```
mcp_backend       id(text PK), owner_login(FK users CASCADE), namespace, name, url,
                  transport, enabled, created_at, updated_at
                  UNIQUE(owner_login, namespace)
   │
   └─1..N─ mcp_backend_key   id(text PK), backend_id(FK CASCADE), slug, description,
                             storage_type, secret_value_local(bytea│null),
                             secret_value_vault_ref(text│null), vault_identifier(text│null),
                             enabled, created_at
                             UNIQUE(backend_id, slug)

mcp_apikey        id(text PK), owner_login(FK users CASCADE), token_hash, label,
                  revoked, created_at
   │
   └─N─── mcp_apikey_grant   apikey_id(FK CASCADE), backend_id(FK CASCADE),
                             backend_key_id(FK CASCADE)
                             PK(apikey_id, backend_id)
```

---

## Task 1 : Tables + migration

**Files:**
- Modify: `backend/src/portal/db/tables.py` (ajout en fin de fichier)
- Create: `backend/alembic/versions/017_mcp_gateway.py`
- Test: `backend/tests/db/test_mcp.py` (création + smoke)

**Interfaces:**
- Produces: objets Table `mcp_backend`, `mcp_backend_key`, `mcp_apikey`, `mcp_apikey_grant` importables depuis `portal.db.tables`.

- [ ] **Step 1 : Écrire le test de smoke des tables**

Créer `backend/tests/db/test_mcp.py` :

```python
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.tables import (
    mcp_apikey,
    mcp_apikey_grant,
    mcp_backend,
    mcp_backend_key,
    users,
)

pytestmark = pytest.mark.asyncio


async def _user(conn: AsyncConnection, login: str = "alice") -> None:
    await conn.execute(insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4())))


async def test_tables_smoke(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await db_conn.execute(
        insert(mcp_backend).values(
            id="b1", owner_login="alice", namespace="rag",
            name="RAG", url="https://rag.yoops.org/mcp", transport="streamable_http",
        )
    )
    await db_conn.execute(
        insert(mcp_backend_key).values(
            id="k1", backend_id="b1", slug="read", description="lecture seule",
            storage_type="local", secret_value_local=b"\x00" * 16,
        )
    )
    await db_conn.execute(insert(mcp_apikey).values(id="a1", owner_login="alice", token_hash="h", label="cli"))
    await db_conn.execute(
        insert(mcp_apikey_grant).values(apikey_id="a1", backend_id="b1", backend_key_id="k1")
    )
    rows = (await db_conn.execute(select(mcp_backend.c.namespace))).all()
    assert rows == [("rag",)]
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `cd backend && uv run pytest tests/db/test_mcp.py::test_tables_smoke -v`
Expected: FAIL avec `ImportError: cannot import name 'mcp_backend'`.

- [ ] **Step 3 : Ajouter les tables dans `tables.py`**

Ajouter à la fin de `backend/src/portal/db/tables.py` (les imports `Table, Column, Text, Boolean, DateTime, LargeBinary, ForeignKey, UniqueConstraint, func` sont déjà présents) :

```python
# ─── MCP Gateway (lot 1) ──────────────────────────────────────────────────────

mcp_backend = Table(
    "mcp_backend",
    metadata,
    Column("id", Text, primary_key=True),
    Column("owner_login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("namespace", Text, nullable=False),  # préfixe ^[a-z0-9_]+ sans "__"
    Column("name", Text, nullable=False),
    Column("url", Text, nullable=False),
    Column("transport", Text, nullable=False, server_default="streamable_http"),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("owner_login", "namespace", name="uq_mcp_backend_owner_namespace"),
)

mcp_backend_key = Table(
    "mcp_backend_key",
    metadata,
    Column("id", Text, primary_key=True),
    Column("backend_id", Text, ForeignKey("mcp_backend.id", ondelete="CASCADE"), nullable=False),
    Column("slug", Text, nullable=False),  # clef fonctionnelle, ex 'read'/'admin'
    Column("description", Text, nullable=False, server_default=""),
    Column("storage_type", Text, nullable=False),  # 'local' | 'harpocrate'
    Column("secret_value_local", LargeBinary, nullable=True),
    Column("secret_value_vault_ref", Text, nullable=True),
    Column("vault_identifier", Text, nullable=True),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("backend_id", "slug", name="uq_mcp_backend_key_backend_slug"),
)

mcp_apikey = Table(
    "mcp_apikey",
    metadata,
    Column("id", Text, primary_key=True),
    Column("owner_login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("token_hash", Text, nullable=False),  # sha256 hex du token clair
    Column("label", Text, nullable=False, server_default=""),
    Column("revoked", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

mcp_apikey_grant = Table(
    "mcp_apikey_grant",
    metadata,
    Column("apikey_id", Text, ForeignKey("mcp_apikey.id", ondelete="CASCADE"), nullable=False),
    Column("backend_id", Text, ForeignKey("mcp_backend.id", ondelete="CASCADE"), nullable=False),
    Column(
        "backend_key_id",
        Text,
        ForeignKey("mcp_backend_key.id", ondelete="CASCADE"),
        nullable=False,
    ),
    UniqueConstraint("apikey_id", "backend_id", name="pk_mcp_apikey_grant"),
)
```

> Note : `mcp_apikey_grant` utilise une `UniqueConstraint` sur `(apikey_id, backend_id)` plutôt qu'une PK composite, pour rester homogène avec le style déclaratif du fichier (les autres tables de liaison du projet font de même). L'invariant « un seul grant par (apikey, backend) » est garanti.

- [ ] **Step 4 : Écrire la migration `017_mcp_gateway.py`**

Créer `backend/alembic/versions/017_mcp_gateway.py` :

```python
"""mcp gateway lot 1 : backends, clés de service, apikeys clients, grants.

Revision ID: 017
Revises: 016
Create Date: 2026-06-22
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "017"
down_revision: str | None = "016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_backend",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("owner_login", sa.Text(), sa.ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("transport", sa.Text(), nullable=False, server_default="streamable_http"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("owner_login", "namespace", name="uq_mcp_backend_owner_namespace"),
    )
    op.create_table(
        "mcp_backend_key",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("backend_id", sa.Text(), sa.ForeignKey("mcp_backend.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("storage_type", sa.Text(), nullable=False),
        sa.Column("secret_value_local", sa.LargeBinary(), nullable=True),
        sa.Column("secret_value_vault_ref", sa.Text(), nullable=True),
        sa.Column("vault_identifier", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("backend_id", "slug", name="uq_mcp_backend_key_backend_slug"),
    )
    op.create_table(
        "mcp_apikey",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("owner_login", sa.Text(), sa.ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False, server_default=""),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "mcp_apikey_grant",
        sa.Column("apikey_id", sa.Text(), sa.ForeignKey("mcp_apikey.id", ondelete="CASCADE"), nullable=False),
        sa.Column("backend_id", sa.Text(), sa.ForeignKey("mcp_backend.id", ondelete="CASCADE"), nullable=False),
        sa.Column("backend_key_id", sa.Text(), sa.ForeignKey("mcp_backend_key.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("apikey_id", "backend_id", name="pk_mcp_apikey_grant"),
    )


def downgrade() -> None:
    op.drop_table("mcp_apikey_grant")
    op.drop_table("mcp_apikey")
    op.drop_table("mcp_backend_key")
    op.drop_table("mcp_backend")
```

- [ ] **Step 5 : Lancer le test, vérifier le succès**

Run: `cd backend && uv run pytest tests/db/test_mcp.py::test_tables_smoke -v`
Expected: PASS (skip si Docker absent).

- [ ] **Step 6 : Lint + commit**

```bash
cd backend && uv run ruff check src/portal/db/tables.py alembic/versions/017_mcp_gateway.py tests/db/test_mcp.py && uv run mypy src/portal/db/tables.py
cd .. && git add backend/src/portal/db/tables.py backend/alembic/versions/017_mcp_gateway.py backend/tests/db/test_mcp.py
git commit -m "feat(mcp): tables registre passerelle MCP + migration 017"
```

---

## Task 2 : Couche DB — backends

**Files:**
- Create: `backend/src/portal/db/mcp.py`
- Test: `backend/tests/db/test_mcp.py` (ajout)

**Interfaces:**
- Consumes: tables de Task 1.
- Produces:
  - `async def insert_backend(conn, *, id: str, owner_login: str, namespace: str, name: str, url: str, transport: str) -> None`
  - `async def list_backends(conn, owner_login: str) -> list[dict[str, Any]]`
  - `async def get_backend(conn, owner_login: str, backend_id: str) -> dict[str, Any] | None`
  - `async def update_backend(conn, owner_login, backend_id, *, name, url, transport, enabled) -> bool`
  - `async def delete_backend(conn, owner_login, backend_id) -> bool`

- [ ] **Step 1 : Écrire les tests CRUD backend**

Ajouter à `backend/tests/db/test_mcp.py` :

```python
from portal.db.mcp import (
    delete_backend,
    get_backend,
    insert_backend,
    list_backends,
    update_backend,
)


async def test_backend_crud(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await insert_backend(
        db_conn, id="b1", owner_login="alice", namespace="rag",
        name="RAG", url="https://rag/mcp", transport="streamable_http",
    )
    rows = await list_backends(db_conn, "alice")
    assert len(rows) == 1 and rows[0]["namespace"] == "rag"
    assert "owner_login" in rows[0]

    got = await get_backend(db_conn, "alice", "b1")
    assert got is not None and got["name"] == "RAG"

    # isolation : bob ne voit rien
    await _user(db_conn, "bob")
    assert await get_backend(db_conn, "bob", "b1") is None
    assert await list_backends(db_conn, "bob") == []

    ok = await update_backend(
        db_conn, "alice", "b1", name="RAG2", url="https://rag2/mcp",
        transport="sse", enabled=False,
    )
    assert ok is True
    got = await get_backend(db_conn, "alice", "b1")
    assert got["name"] == "RAG2" and got["enabled"] is False

    assert await delete_backend(db_conn, "alice", "b1") is True
    assert await get_backend(db_conn, "alice", "b1") is None
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `cd backend && uv run pytest tests/db/test_mcp.py::test_backend_crud -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'portal.db.mcp'`.

- [ ] **Step 3 : Implémenter les fonctions backend dans `db/mcp.py`**

Créer `backend/src/portal/db/mcp.py` :

```python
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import mcp_apikey, mcp_apikey_grant, mcp_backend, mcp_backend_key

_BACKEND_COLS = [
    mcp_backend.c.id,
    mcp_backend.c.owner_login,
    mcp_backend.c.namespace,
    mcp_backend.c.name,
    mcp_backend.c.url,
    mcp_backend.c.transport,
    mcp_backend.c.enabled,
    mcp_backend.c.created_at,
    mcp_backend.c.updated_at,
]


async def insert_backend(
    conn: AsyncConnection,
    *,
    id: str,
    owner_login: str,
    namespace: str,
    name: str,
    url: str,
    transport: str,
) -> None:
    await conn.execute(
        insert(mcp_backend).values(
            id=id,
            owner_login=owner_login,
            namespace=namespace,
            name=name,
            url=url,
            transport=transport,
        )
    )


async def list_backends(conn: AsyncConnection, owner_login: str) -> list[dict[str, Any]]:
    q = (
        select(*_BACKEND_COLS)
        .where(mcp_backend.c.owner_login == owner_login)
        .order_by(mcp_backend.c.created_at)
    )
    return [dict(r) for r in (await conn.execute(q)).mappings().all()]


async def get_backend(
    conn: AsyncConnection, owner_login: str, backend_id: str
) -> dict[str, Any] | None:
    q = select(*_BACKEND_COLS).where(
        mcp_backend.c.id == backend_id,
        mcp_backend.c.owner_login == owner_login,
    )
    row = (await conn.execute(q)).mappings().first()
    return dict(row) if row else None


async def update_backend(
    conn: AsyncConnection,
    owner_login: str,
    backend_id: str,
    *,
    name: str,
    url: str,
    transport: str,
    enabled: bool,
) -> bool:
    from sqlalchemy import func as _func

    q = (
        update(mcp_backend)
        .where(mcp_backend.c.id == backend_id, mcp_backend.c.owner_login == owner_login)
        .values(name=name, url=url, transport=transport, enabled=enabled, updated_at=_func.now())
        .returning(mcp_backend.c.id)
    )
    return (await conn.execute(q)).first() is not None


async def delete_backend(conn: AsyncConnection, owner_login: str, backend_id: str) -> bool:
    q = (
        delete(mcp_backend)
        .where(mcp_backend.c.id == backend_id, mcp_backend.c.owner_login == owner_login)
        .returning(mcp_backend.c.id)
    )
    return (await conn.execute(q)).first() is not None
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run: `cd backend && uv run pytest tests/db/test_mcp.py::test_backend_crud -v`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add backend/src/portal/db/mcp.py backend/tests/db/test_mcp.py
git commit -m "feat(mcp): couche DB CRUD backends"
```

---

## Task 3 : Couche DB — clés de service & grants & apikeys

**Files:**
- Modify: `backend/src/portal/db/mcp.py`
- Test: `backend/tests/db/test_mcp.py` (ajout)

**Interfaces:**
- Produces:
  - `async def insert_backend_key(conn, *, id, backend_id, slug, description, storage_type, secret_value_local: bytes | None, secret_value_vault_ref: str | None, vault_identifier: str | None) -> None`
  - `async def list_backend_keys(conn, backend_id: str) -> list[dict]` (jamais `secret_value_local`)
  - `async def get_backend_key(conn, backend_id: str, key_id: str) -> dict | None`
  - `async def delete_backend_key(conn, backend_id: str, key_id: str) -> bool`
  - `async def insert_apikey(conn, *, id, owner_login, token_hash, label) -> None`
  - `async def list_apikeys(conn, owner_login: str) -> list[dict]` (jamais `token_hash`)
  - `async def find_apikey_by_hash(conn, token_hash: str) -> dict | None`
  - `async def revoke_apikey(conn, owner_login, apikey_id) -> bool`
  - `async def delete_apikey(conn, owner_login, apikey_id) -> bool`
  - `async def set_grant(conn, *, apikey_id, backend_id, backend_key_id) -> None` (upsert)
  - `async def list_grants(conn, apikey_id: str) -> list[dict]`
  - `async def delete_grant(conn, apikey_id, backend_id) -> bool`

- [ ] **Step 1 : Écrire les tests (clés sans valeur exposée, apikeys sans hash, grants upsert)**

Ajouter à `backend/tests/db/test_mcp.py` :

```python
from portal.db.mcp import (
    delete_apikey,
    delete_backend_key,
    delete_grant,
    find_apikey_by_hash,
    get_backend_key,
    insert_apikey,
    insert_backend_key,
    list_apikeys,
    list_backend_keys,
    list_grants,
    revoke_apikey,
    set_grant,
)


async def test_backend_key_never_exposes_local_value(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await insert_backend(
        db_conn, id="b1", owner_login="alice", namespace="rag",
        name="RAG", url="https://rag/mcp", transport="streamable_http",
    )
    await insert_backend_key(
        db_conn, id="k1", backend_id="b1", slug="read", description="ro",
        storage_type="local", secret_value_local=b"\xDE\xAD" * 8,
        secret_value_vault_ref=None, vault_identifier=None,
    )
    rows = await list_backend_keys(db_conn, "b1")
    assert len(rows) == 1 and rows[0]["slug"] == "read"
    assert "secret_value_local" not in rows[0]
    got = await get_backend_key(db_conn, "b1", "k1")
    assert got is not None and "secret_value_local" not in got
    assert await delete_backend_key(db_conn, "b1", "k1") is True


async def test_apikey_lifecycle_and_grants(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await insert_backend(
        db_conn, id="b1", owner_login="alice", namespace="rag",
        name="RAG", url="https://rag/mcp", transport="streamable_http",
    )
    await insert_backend_key(
        db_conn, id="k1", backend_id="b1", slug="read", description="",
        storage_type="local", secret_value_local=b"x", secret_value_vault_ref=None,
        vault_identifier=None,
    )
    await insert_apikey(db_conn, id="a1", owner_login="alice", token_hash="HASH", label="cli")

    rows = await list_apikeys(db_conn, "alice")
    assert len(rows) == 1 and "token_hash" not in rows[0]

    found = await find_apikey_by_hash(db_conn, "HASH")
    assert found is not None and found["id"] == "a1" and found["owner_login"] == "alice"

    await set_grant(db_conn, apikey_id="a1", backend_id="b1", backend_key_id="k1")
    # upsert : re-set sur le même (apikey, backend) remplace la clé sans doublon
    await set_grant(db_conn, apikey_id="a1", backend_id="b1", backend_key_id="k1")
    grants = await list_grants(db_conn, "a1")
    assert len(grants) == 1 and grants[0]["backend_key_id"] == "k1"

    assert await delete_grant(db_conn, "a1", "b1") is True
    assert await list_grants(db_conn, "a1") == []

    assert await revoke_apikey(db_conn, "alice", "a1") is True
    assert await delete_apikey(db_conn, "alice", "a1") is True
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `cd backend && uv run pytest tests/db/test_mcp.py -k "key_never or lifecycle" -v`
Expected: FAIL (ImportError sur les nouvelles fonctions).

- [ ] **Step 3 : Implémenter dans `db/mcp.py`**

Ajouter à `backend/src/portal/db/mcp.py` (compléter l'import du haut : `from sqlalchemy.dialects.postgresql import insert as pg_insert`) :

```python
_KEY_COLS = [
    mcp_backend_key.c.id,
    mcp_backend_key.c.backend_id,
    mcp_backend_key.c.slug,
    mcp_backend_key.c.description,
    mcp_backend_key.c.storage_type,
    mcp_backend_key.c.secret_value_vault_ref,
    mcp_backend_key.c.vault_identifier,
    mcp_backend_key.c.enabled,
    mcp_backend_key.c.created_at,
]

_APIKEY_COLS = [
    mcp_apikey.c.id,
    mcp_apikey.c.owner_login,
    mcp_apikey.c.label,
    mcp_apikey.c.revoked,
    mcp_apikey.c.created_at,
]


async def insert_backend_key(
    conn: AsyncConnection,
    *,
    id: str,
    backend_id: str,
    slug: str,
    description: str,
    storage_type: str,
    secret_value_local: bytes | None,
    secret_value_vault_ref: str | None,
    vault_identifier: str | None,
) -> None:
    await conn.execute(
        insert(mcp_backend_key).values(
            id=id,
            backend_id=backend_id,
            slug=slug,
            description=description,
            storage_type=storage_type,
            secret_value_local=secret_value_local,
            secret_value_vault_ref=secret_value_vault_ref,
            vault_identifier=vault_identifier,
        )
    )


async def list_backend_keys(conn: AsyncConnection, backend_id: str) -> list[dict[str, Any]]:
    q = (
        select(*_KEY_COLS)
        .where(mcp_backend_key.c.backend_id == backend_id)
        .order_by(mcp_backend_key.c.created_at)
    )
    return [dict(r) for r in (await conn.execute(q)).mappings().all()]


async def get_backend_key(
    conn: AsyncConnection, backend_id: str, key_id: str
) -> dict[str, Any] | None:
    q = select(*_KEY_COLS).where(
        mcp_backend_key.c.id == key_id,
        mcp_backend_key.c.backend_id == backend_id,
    )
    row = (await conn.execute(q)).mappings().first()
    return dict(row) if row else None


async def delete_backend_key(conn: AsyncConnection, backend_id: str, key_id: str) -> bool:
    q = (
        delete(mcp_backend_key)
        .where(mcp_backend_key.c.id == key_id, mcp_backend_key.c.backend_id == backend_id)
        .returning(mcp_backend_key.c.id)
    )
    return (await conn.execute(q)).first() is not None


async def insert_apikey(
    conn: AsyncConnection, *, id: str, owner_login: str, token_hash: str, label: str
) -> None:
    await conn.execute(
        insert(mcp_apikey).values(
            id=id, owner_login=owner_login, token_hash=token_hash, label=label
        )
    )


async def list_apikeys(conn: AsyncConnection, owner_login: str) -> list[dict[str, Any]]:
    q = (
        select(*_APIKEY_COLS)
        .where(mcp_apikey.c.owner_login == owner_login)
        .order_by(mcp_apikey.c.created_at)
    )
    return [dict(r) for r in (await conn.execute(q)).mappings().all()]


async def find_apikey_by_hash(conn: AsyncConnection, token_hash: str) -> dict[str, Any] | None:
    q = select(*_APIKEY_COLS, mcp_apikey.c.token_hash).where(
        mcp_apikey.c.token_hash == token_hash,
        mcp_apikey.c.revoked.is_(False),
    )
    row = (await conn.execute(q)).mappings().first()
    return dict(row) if row else None


async def revoke_apikey(conn: AsyncConnection, owner_login: str, apikey_id: str) -> bool:
    q = (
        update(mcp_apikey)
        .where(mcp_apikey.c.id == apikey_id, mcp_apikey.c.owner_login == owner_login)
        .values(revoked=True)
        .returning(mcp_apikey.c.id)
    )
    return (await conn.execute(q)).first() is not None


async def delete_apikey(conn: AsyncConnection, owner_login: str, apikey_id: str) -> bool:
    q = (
        delete(mcp_apikey)
        .where(mcp_apikey.c.id == apikey_id, mcp_apikey.c.owner_login == owner_login)
        .returning(mcp_apikey.c.id)
    )
    return (await conn.execute(q)).first() is not None


async def set_grant(
    conn: AsyncConnection, *, apikey_id: str, backend_id: str, backend_key_id: str
) -> None:
    stmt = pg_insert(mcp_apikey_grant).values(
        apikey_id=apikey_id, backend_id=backend_id, backend_key_id=backend_key_id
    )
    stmt = stmt.on_conflict_do_update(
        constraint="pk_mcp_apikey_grant",
        set_={"backend_key_id": backend_key_id},
    )
    await conn.execute(stmt)


async def list_grants(conn: AsyncConnection, apikey_id: str) -> list[dict[str, Any]]:
    q = select(
        mcp_apikey_grant.c.apikey_id,
        mcp_apikey_grant.c.backend_id,
        mcp_apikey_grant.c.backend_key_id,
    ).where(mcp_apikey_grant.c.apikey_id == apikey_id)
    return [dict(r) for r in (await conn.execute(q)).mappings().all()]


async def delete_grant(conn: AsyncConnection, apikey_id: str, backend_id: str) -> bool:
    q = (
        delete(mcp_apikey_grant)
        .where(
            mcp_apikey_grant.c.apikey_id == apikey_id,
            mcp_apikey_grant.c.backend_id == backend_id,
        )
        .returning(mcp_apikey_grant.c.apikey_id)
    )
    return (await conn.execute(q)).first() is not None
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run: `cd backend && uv run pytest tests/db/test_mcp.py -v`
Expected: tous PASS.

- [ ] **Step 5 : Lint + commit**

```bash
cd backend && uv run ruff check src/portal/db/mcp.py tests/db/test_mcp.py && uv run mypy src/portal/db/mcp.py
cd .. && git add backend/src/portal/db/mcp.py backend/tests/db/test_mcp.py
git commit -m "feat(mcp): couche DB clés de service, apikeys clients, grants"
```

---

## Task 4 : SecretResolver (Protocol + EnvSecretResolver)

**Files:**
- Modify: `backend/src/portal/secrets/resolver.py`
- Test: `backend/tests/secrets/test_resolver_protocol.py`

**Interfaces:**
- Produces:
  - `class SecretResolver(Protocol): async def resolve(self, ref: str) -> Secret`
  - `class EnvSecretResolver:` implémente `resolve`, lit `${env://NOM}` via `os.environ`, lève `SecretAccessError` si absent ou format invalide.

- [ ] **Step 1 : Écrire le test**

Créer `backend/tests/secrets/test_resolver_protocol.py` :

```python
from __future__ import annotations

import pytest

from portal.secrets.resolver import EnvSecretResolver, SecretAccessError, SecretResolver
from portal.secrets.types import Secret

pytestmark = pytest.mark.asyncio


async def test_env_resolver_resolves(monkeypatch) -> None:
    monkeypatch.setenv("MCP_RAG_TOKEN", "s3cr3t")
    r = EnvSecretResolver()
    out = await r.resolve("${env://MCP_RAG_TOKEN}")
    assert isinstance(out, Secret)
    assert out.reveal() == "s3cr3t"
    # le repr ne fuit jamais la valeur
    assert "s3cr3t" not in repr(out)


async def test_env_resolver_missing_var(monkeypatch) -> None:
    monkeypatch.delenv("MCP_ABSENT", raising=False)
    with pytest.raises(SecretAccessError):
        await EnvSecretResolver().resolve("${env://MCP_ABSENT}")


async def test_env_resolver_rejects_non_env_ref() -> None:
    with pytest.raises(SecretAccessError):
        await EnvSecretResolver().resolve("${vault://foo/bar}")


def test_env_resolver_satisfies_protocol() -> None:
    assert isinstance(EnvSecretResolver(), SecretResolver)
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `cd backend && uv run pytest tests/secrets/test_resolver_protocol.py -v`
Expected: FAIL (`ImportError` sur `EnvSecretResolver`/`SecretResolver`).

- [ ] **Step 3 : Ajouter le Protocol + EnvSecretResolver dans `resolver.py`**

Ajouter en bas de `backend/src/portal/secrets/resolver.py` (compléter l'import du haut : `from typing import Literal, Protocol, runtime_checkable`) :

```python
@runtime_checkable
class SecretResolver(Protocol):
    """Résout une référence ${vault://...} ou ${env://NOM} en valeur claire (spec §6)."""

    async def resolve(self, ref: str) -> Secret: ...


class EnvSecretResolver:
    """Palier de résolution : ne gère que ${env://NOM} (spec §6).

    Suffit pour le lot 1 ; le contrat ne change pas quand le gestionnaire de
    secrets cible (vault) sera branché via un autre implémenteur du Protocol.
    """

    async def resolve(self, ref: str) -> Secret:
        m = _SECRET_REF_RE.fullmatch(ref)
        if not m or m.group(1) != "env":
            raise SecretAccessError(f"EnvSecretResolver ne résout que ${{env://...}} : {ref!r}")
        name = m.group(2)
        value = os.environ.get(name)
        if value is None:
            raise SecretAccessError(f"Environment variable not found: {name!r}")
        return Secret(value)
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run: `cd backend && uv run pytest tests/secrets/test_resolver_protocol.py -v`
Expected: tous PASS.

- [ ] **Step 5 : Lint + commit**

```bash
cd backend && uv run ruff check src/portal/secrets/resolver.py tests/secrets/test_resolver_protocol.py && uv run mypy src/portal/secrets/resolver.py
cd .. && git add backend/src/portal/secrets/resolver.py backend/tests/secrets/test_resolver_protocol.py
git commit -m "feat(mcp): SecretResolver Protocol + EnvSecretResolver (fondation runtime)"
```

---

## Task 5 : Modèles pydantic + service backends (validation)

**Files:**
- Create: `backend/src/portal/mcp/__init__.py` (vide)
- Create: `backend/src/portal/mcp/models.py`
- Create: `backend/src/portal/mcp/service.py`
- Test: `backend/tests/mcp/__init__.py` (vide), `backend/tests/mcp/test_service.py`

**Interfaces:**
- Produces:
  - `models.NAMESPACE_RE`, `models.SLUG_RE` (compiled regex)
  - `models.BackendCreate` (pydantic : `namespace`, `name`, `url`, `transport` ∈ {streamable_http,sse,stdio}) avec validateurs
  - `models.BackendUpdate` (`name`, `url`, `transport`, `enabled`)
  - `service.new_id() -> str`
  - `service.MCPError`, `service.NamespaceTaken`, `service.NotFound`, `service.InvalidReference`
  - `async def service.create_backend(conn, owner_login, body: BackendCreate) -> str` (retourne l'id)

- [ ] **Step 1 : Écrire les tests modèles + service backend**

Créer `backend/tests/mcp/__init__.py` (vide) puis `backend/tests/mcp/test_service.py` :

```python
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import get_backend, list_backends
from portal.db.tables import users
from portal.mcp import models, service

pytestmark = pytest.mark.asyncio


async def _user(conn: AsyncConnection, login: str = "alice") -> None:
    await conn.execute(insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4())))


def test_namespace_rejects_double_underscore() -> None:
    with pytest.raises(ValueError):
        models.BackendCreate(namespace="rag__x", name="n", url="https://x/mcp", transport="streamable_http")


def test_namespace_rejects_uppercase() -> None:
    with pytest.raises(ValueError):
        models.BackendCreate(namespace="RAG", name="n", url="https://x/mcp", transport="streamable_http")


def test_transport_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        models.BackendCreate(namespace="rag", name="n", url="https://x/mcp", transport="grpc")


def test_namespace_accepts_single_underscore() -> None:
    b = models.BackendCreate(namespace="rag_v2", name="n", url="https://x/mcp", transport="sse")
    assert b.namespace == "rag_v2"


async def test_create_backend_then_duplicate_namespace(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    body = models.BackendCreate(namespace="rag", name="RAG", url="https://rag/mcp", transport="streamable_http")
    bid = await service.create_backend(db_conn, "alice", body)
    assert (await get_backend(db_conn, "alice", bid))["namespace"] == "rag"

    with pytest.raises(service.NamespaceTaken):
        await service.create_backend(db_conn, "alice", body)
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `cd backend && uv run pytest tests/mcp/test_service.py -v`
Expected: FAIL (`ModuleNotFoundError: portal.mcp`).

- [ ] **Step 3 : Créer `mcp/models.py`**

```python
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

NAMESPACE_RE = re.compile(r"^[a-z0-9_]{1,40}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")

Transport = Literal["streamable_http", "sse", "stdio"]


def _validate_namespace(v: str) -> str:
    if not NAMESPACE_RE.fullmatch(v):
        raise ValueError("namespace: minuscules/chiffres/underscore, 1 à 40 caractères")
    if "__" in v:
        raise ValueError("namespace: '__' est réservé au séparateur de namespacing")
    return v


class BackendCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    namespace: str
    name: str
    url: str
    transport: Transport = "streamable_http"

    @field_validator("namespace")
    @classmethod
    def _ns(cls, v: str) -> str:
        return _validate_namespace(v)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        if not (v.startswith("https://") or v.startswith("http://")):
            raise ValueError("url: doit commencer par http:// ou https://")
        return v


class BackendUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    url: str
    transport: Transport
    enabled: bool

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        if not (v.startswith("https://") or v.startswith("http://")):
            raise ValueError("url: doit commencer par http:// ou https://")
        return v
```

- [ ] **Step 4 : Créer `mcp/__init__.py` (vide) et `mcp/service.py` (partie backends)**

`backend/src/portal/mcp/__init__.py` : fichier vide.

`backend/src/portal/mcp/service.py` :

```python
from __future__ import annotations

import uuid

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db import mcp as db
from .models import BackendCreate

_log = structlog.get_logger(__name__)


class MCPError(Exception):
    pass


class NamespaceTaken(MCPError):
    pass


class NotFound(MCPError):
    pass


class InvalidReference(MCPError):
    pass


def new_id() -> str:
    return uuid.uuid4().hex


async def create_backend(conn: AsyncConnection, owner_login: str, body: BackendCreate) -> str:
    bid = new_id()
    try:
        await db.insert_backend(
            conn,
            id=bid,
            owner_login=owner_login,
            namespace=body.namespace,
            name=body.name,
            url=body.url,
            transport=body.transport,
        )
    except IntegrityError as exc:
        raise NamespaceTaken(f"namespace '{body.namespace}' déjà utilisé") from exc
    _log.info("mcp_backend_created", login=owner_login, namespace=body.namespace)
    return bid
```

- [ ] **Step 5 : Lancer, vérifier le succès**

Run: `cd backend && uv run pytest tests/mcp/test_service.py -v`
Expected: tous PASS.

- [ ] **Step 6 : Lint + commit**

```bash
cd backend && uv run ruff check src/portal/mcp/ tests/mcp/ && uv run mypy src/portal/mcp/
cd .. && git add backend/src/portal/mcp/ backend/tests/mcp/
git commit -m "feat(mcp): modèles pydantic + service create_backend avec validation namespace"
```

---

## Task 6 : Service — clés de service (stockage local chiffré / wallet référence)

**Files:**
- Modify: `backend/src/portal/mcp/models.py`, `backend/src/portal/mcp/service.py`
- Test: `backend/tests/mcp/test_service.py` (ajout)

**Interfaces:**
- Consumes: `vault.session.get_master_key`, `vault.crypto.encrypt_token`, `db.insert_backend_key`, `db.get_backend`.
- Produces:
  - `models.KeyCreate` (`slug`, `description`, `storage_type` ∈ {local,harpocrate}, `secret_value: str`, `vault_identifier: str | None`)
  - `service.VaultLocked(MCPError)`
  - `async def service.create_backend_key(conn, owner_login, backend_id, session_id, body: KeyCreate) -> str`

- [ ] **Step 1 : Écrire les tests (local chiffré ; backend d'autrui interdit ; vault locked)**

Ajouter à `backend/tests/mcp/test_service.py` :

```python
from portal.db.mcp import list_backend_keys
from portal.db.tables import mcp_backend_key
from sqlalchemy import select
from portal.vault import session as vault_session
from portal.vault.crypto import decrypt_token


async def test_create_local_key_encrypts_value(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    body_b = models.BackendCreate(namespace="rag", name="RAG", url="https://rag/mcp", transport="streamable_http")
    bid = await service.create_backend(db_conn, "alice", body_b)

    mk = b"\x11" * 32
    sid = "sess-alice"
    vault_session.set_master_key(sid, mk)
    try:
        key_body = models.KeyCreate(
            slug="read", description="ro", storage_type="local",
            secret_value="rag-token-123", vault_identifier=None,
        )
        kid = await service.create_backend_key(db_conn, "alice", bid, sid, key_body)
    finally:
        vault_session.clear_session(sid)

    # la liste n'expose jamais la valeur
    rows = await list_backend_keys(db_conn, bid)
    assert rows[0]["slug"] == "read" and "secret_value_local" not in rows[0]

    # la valeur stockée est bien chiffrée et redéchiffrable avec la master_key
    blob = (
        await db_conn.execute(
            select(mcp_backend_key.c.secret_value_local).where(mcp_backend_key.c.id == kid)
        )
    ).scalar_one()
    assert blob != b"rag-token-123"
    assert decrypt_token(blob, mk) == "rag-token-123"


async def test_create_key_on_foreign_backend_denied(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await _user(db_conn, "bob")
    bid = await service.create_backend(
        db_conn, "alice",
        models.BackendCreate(namespace="rag", name="RAG", url="https://rag/mcp", transport="streamable_http"),
    )
    sid = "sess-bob"
    vault_session.set_master_key(sid, b"\x22" * 32)
    try:
        with pytest.raises(service.NotFound):
            await service.create_backend_key(
                db_conn, "bob", bid, sid,
                models.KeyCreate(slug="x", description="", storage_type="local",
                                 secret_value="v", vault_identifier=None),
            )
    finally:
        vault_session.clear_session(sid)


async def test_create_local_key_requires_unlocked_vault(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    bid = await service.create_backend(
        db_conn, "alice",
        models.BackendCreate(namespace="rag", name="RAG", url="https://rag/mcp", transport="streamable_http"),
    )
    with pytest.raises(service.VaultLocked):
        await service.create_backend_key(
            db_conn, "alice", bid, "no-session",
            models.KeyCreate(slug="read", description="", storage_type="local",
                             secret_value="v", vault_identifier=None),
        )
```

> Helpers de session confirmés dans `portal/vault/session.py` : `set_master_key(session_id, key)`, `get_master_key(session_id) -> bytes | None`, `clear_session(session_id)`. (Pas de `clear_master_key`.)

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `cd backend && uv run pytest tests/mcp/test_service.py -k "key" -v`
Expected: FAIL.

- [ ] **Step 3 : Ajouter `KeyCreate` dans `models.py`**

```python
class KeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    description: str = ""
    storage_type: Literal["local", "harpocrate"]
    secret_value: str
    vault_identifier: str | None = None

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not SLUG_RE.fullmatch(v):
            raise ValueError("slug: minuscule initiale, [a-z0-9_-], 1 à 63 caractères")
        return v
```

- [ ] **Step 4 : Ajouter `create_backend_key` + `VaultLocked` dans `service.py`**

Compléter les imports en tête : `from ..vault import session as vault_session`, `from ..vault.crypto import encrypt_token`, `from .models import BackendCreate, KeyCreate`.

```python
class VaultLocked(MCPError):
    pass


async def _require_owned_backend(
    conn: AsyncConnection, owner_login: str, backend_id: str
) -> None:
    if await db.get_backend(conn, owner_login, backend_id) is None:
        raise NotFound(f"backend '{backend_id}' introuvable")


async def create_backend_key(
    conn: AsyncConnection,
    owner_login: str,
    backend_id: str,
    session_id: str,
    body: KeyCreate,
) -> str:
    await _require_owned_backend(conn, owner_login, backend_id)

    local_blob: bytes | None = None
    vault_ref: str | None = None
    vault_id: str | None = None

    if body.storage_type == "local":
        master_key = vault_session.get_master_key(session_id)
        if master_key is None:
            raise VaultLocked("Vault verrouillé — déverrouillez avec votre PIN")
        local_blob = encrypt_token(body.secret_value, master_key)
    else:  # harpocrate : on ne stocke qu'une référence
        if not body.vault_identifier:
            raise InvalidReference("vault_identifier requis pour storage_type='harpocrate'")
        vault_id = body.vault_identifier
        vault_ref = f"${{vault://{body.vault_identifier}:mcp/{backend_id}/{body.slug}}}"

    kid = new_id()
    try:
        await db.insert_backend_key(
            conn,
            id=kid,
            backend_id=backend_id,
            slug=body.slug,
            description=body.description,
            storage_type=body.storage_type,
            secret_value_local=local_blob,
            secret_value_vault_ref=vault_ref,
            vault_identifier=vault_id,
        )
    except IntegrityError as exc:
        raise NamespaceTaken(f"slug '{body.slug}' déjà utilisé pour ce backend") from exc
    _log.info("mcp_backend_key_created", login=owner_login, backend_id=backend_id, slug=body.slug)
    return kid
```

> Note : `NamespaceTaken` est réutilisé pour la collision de slug (même sémantique « identifiant déjà pris »). Le message distingue le cas.

- [ ] **Step 5 : Lancer, vérifier le succès**

Run: `cd backend && uv run pytest tests/mcp/test_service.py -v`
Expected: tous PASS.

- [ ] **Step 6 : Lint + commit**

```bash
cd backend && uv run ruff check src/portal/mcp/ tests/mcp/test_service.py && uv run mypy src/portal/mcp/
cd .. && git add backend/src/portal/mcp/ backend/tests/mcp/test_service.py
git commit -m "feat(mcp): service create_backend_key (local chiffré / wallet référence)"
```

---

## Task 7 : Service — apikeys clients (génération token, hash, grants + garde-fou)

**Files:**
- Modify: `backend/src/portal/mcp/models.py`, `backend/src/portal/mcp/service.py`
- Test: `backend/tests/mcp/test_service.py` (ajout)

**Interfaces:**
- Consumes: `db.insert_apikey`, `db.set_grant`, `db.get_backend`, `db.get_backend_key`.
- Produces:
  - `models.ApikeyCreate` (`label: str`)
  - `models.GrantSet` (`backend_id: str`, `backend_key_id: str`)
  - `service.token_hash(token: str) -> str` (sha256 hex)
  - `service.APIKEY_PREFIX = "mcpk_"`
  - `async def service.create_apikey(conn, owner_login, body) -> tuple[str, str]` → `(apikey_id, token_clair)` ; le clair n'est jamais re-stocké
  - `async def service.set_grant(conn, owner_login, apikey_id, body: GrantSet) -> None` (vérifie que l'apikey, le backend ET la clé appartiennent au user et que la clé est bien sur ce backend)

- [ ] **Step 1 : Écrire les tests (token préfixé + hash ; garde-fou clé↔backend ; isolation owner)**

Ajouter à `backend/tests/mcp/test_service.py` :

```python
from portal.db.mcp import find_apikey_by_hash, insert_apikey, insert_backend_key, list_grants


async def test_create_apikey_returns_clear_once_and_stores_hash(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    aid, clear = await service.create_apikey(db_conn, "alice", models.ApikeyCreate(label="cli"))
    assert clear.startswith(service.APIKEY_PREFIX)
    # le hash stocké correspond au clair ; le clair n'est pas retrouvable autrement
    found = await find_apikey_by_hash(db_conn, service.token_hash(clear))
    assert found is not None and found["id"] == aid


async def test_set_grant_rejects_key_from_other_backend(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    b1 = await service.create_backend(db_conn, "alice",
        models.BackendCreate(namespace="rag", name="RAG", url="https://rag/mcp", transport="streamable_http"))
    b2 = await service.create_backend(db_conn, "alice",
        models.BackendCreate(namespace="wf", name="WF", url="https://wf/mcp", transport="streamable_http"))
    await insert_backend_key(db_conn, id="kB2", backend_id=b2, slug="read", description="",
        storage_type="local", secret_value_local=b"x", secret_value_vault_ref=None, vault_identifier=None)
    aid, _ = await service.create_apikey(db_conn, "alice", models.ApikeyCreate(label="cli"))

    # clé de b2 affectée à un grant sur b1 → refus
    with pytest.raises(service.InvalidReference):
        await service.set_grant(db_conn, "alice", aid,
            models.GrantSet(backend_id=b1, backend_key_id="kB2"))


async def test_set_grant_happy_path(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    b1 = await service.create_backend(db_conn, "alice",
        models.BackendCreate(namespace="rag", name="RAG", url="https://rag/mcp", transport="streamable_http"))
    await insert_backend_key(db_conn, id="kB1", backend_id=b1, slug="read", description="",
        storage_type="local", secret_value_local=b"x", secret_value_vault_ref=None, vault_identifier=None)
    aid, _ = await service.create_apikey(db_conn, "alice", models.ApikeyCreate(label="cli"))
    await service.set_grant(db_conn, "alice", aid, models.GrantSet(backend_id=b1, backend_key_id="kB1"))
    grants = await list_grants(db_conn, aid)
    assert len(grants) == 1 and grants[0]["backend_key_id"] == "kB1"


async def test_set_grant_rejects_foreign_apikey(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await _user(db_conn, "bob")
    b1 = await service.create_backend(db_conn, "alice",
        models.BackendCreate(namespace="rag", name="RAG", url="https://rag/mcp", transport="streamable_http"))
    await insert_backend_key(db_conn, id="kB1", backend_id=b1, slug="read", description="",
        storage_type="local", secret_value_local=b"x", secret_value_vault_ref=None, vault_identifier=None)
    aid, _ = await service.create_apikey(db_conn, "alice", models.ApikeyCreate(label="cli"))
    # bob tente de greffer un grant sur l'apikey d'alice
    with pytest.raises(service.NotFound):
        await service.set_grant(db_conn, "bob", aid, models.GrantSet(backend_id=b1, backend_key_id="kB1"))
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `cd backend && uv run pytest tests/mcp/test_service.py -k "apikey or grant" -v`
Expected: FAIL.

- [ ] **Step 3 : Ajouter `ApikeyCreate` + `GrantSet` dans `models.py`**

```python
class ApikeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = ""


class GrantSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend_id: str
    backend_key_id: str
```

- [ ] **Step 4 : Ajouter la logique apikey/grant dans `service.py`**

Compléter les imports : `import hashlib`, `import secrets as _secrets`, et `from .models import ApikeyCreate, BackendCreate, GrantSet, KeyCreate`.

```python
APIKEY_PREFIX = "mcpk_"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_apikey(
    conn: AsyncConnection, owner_login: str, body: ApikeyCreate
) -> tuple[str, str]:
    clear = APIKEY_PREFIX + _secrets.token_urlsafe(32)
    aid = new_id()
    await db.insert_apikey(
        conn, id=aid, owner_login=owner_login, token_hash=token_hash(clear), label=body.label
    )
    _log.info("mcp_apikey_created", login=owner_login, apikey_id=aid)
    return aid, clear


async def _require_owned_apikey(conn: AsyncConnection, owner_login: str, apikey_id: str) -> None:
    rows = await db.list_apikeys(conn, owner_login)
    if not any(r["id"] == apikey_id for r in rows):
        raise NotFound(f"apikey '{apikey_id}' introuvable")


async def set_grant(
    conn: AsyncConnection, owner_login: str, apikey_id: str, body: GrantSet
) -> None:
    await _require_owned_apikey(conn, owner_login, apikey_id)
    if await db.get_backend(conn, owner_login, body.backend_id) is None:
        raise NotFound(f"backend '{body.backend_id}' introuvable")
    # garde-fou : la clé doit exister ET appartenir au backend du grant
    if await db.get_backend_key(conn, body.backend_id, body.backend_key_id) is None:
        raise InvalidReference("backend_key_id n'appartient pas à ce backend")
    await db.set_grant(
        conn, apikey_id=apikey_id, backend_id=body.backend_id, backend_key_id=body.backend_key_id
    )
    _log.info("mcp_grant_set", login=owner_login, apikey_id=apikey_id, backend_id=body.backend_id)
```

- [ ] **Step 5 : Lancer, vérifier le succès**

Run: `cd backend && uv run pytest tests/mcp/test_service.py -v`
Expected: tous PASS.

- [ ] **Step 6 : Lint + commit**

```bash
cd backend && uv run ruff check src/portal/mcp/ tests/mcp/test_service.py && uv run mypy src/portal/mcp/
cd .. && git add backend/src/portal/mcp/ backend/tests/mcp/test_service.py
git commit -m "feat(mcp): service apikeys clients (token+hash) et grants avec garde-fou clé↔backend"
```

---

## Task 8 : Routes `/me/mcp` + enregistrement

**Files:**
- Create: `backend/src/portal/routes/mcp.py`
- Modify: `backend/src/portal/app.py`
- Test: `backend/tests/routes/test_mcp_routes.py`

**Interfaces:**
- Consumes: `auth.rbac.require_user`, `db.engine.get_conn`, tout le module `mcp.service`, `db.mcp` (listings).
- Produces: `router` (APIRouter) monté avec `prefix="/me"`. Endpoints :
  - `GET /me/mcp/backends` · `POST /me/mcp/backends` · `PATCH /me/mcp/backends/{backend_id}` · `DELETE /me/mcp/backends/{backend_id}`
  - `GET /me/mcp/backends/{backend_id}/keys` · `POST .../keys` · `DELETE .../keys/{key_id}`
  - `GET /me/mcp/apikeys` · `POST /me/mcp/apikeys` (retourne le clair une fois) · `POST /me/mcp/apikeys/{apikey_id}/revoke` · `DELETE /me/mcp/apikeys/{apikey_id}`
  - `GET /me/mcp/apikeys/{apikey_id}/grants` · `PUT .../grants` · `DELETE .../grants/{backend_id}`

- [ ] **Step 1 : Écrire les tests d'intégration**

> **Pattern confirmé** : les tests routes du projet construisent l'app localement et injectent les dépendances via `app.dependency_overrides`. Les routes MCP utilisent `get_conn`, donc le test override `get_conn` pour qu'il yield la `db_conn` du testcontainer, et `require_user` pour authentifier `alice`. On utilise `httpx.AsyncClient` + `ASGITransport` (async, comme `tests/routes/test_plugins.py`). Le `session_id`/vault déverrouillé n'est **pas** simulé ici : la logique de chiffrement local est déjà couverte par les tests service (Task 6). Pour disposer d'une clé sans passer par le vault, on l'insère via le helper DB `insert_backend_key`.

Créer `backend/tests/routes/test_mcp_routes.py` :

```python
from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import insert_backend_key
from portal.db.tables import users

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def client(db_conn: AsyncConnection) -> AsyncGenerator[AsyncClient, None]:
    # App minimale avec le seul routeur MCP — évite SessionMiddleware/OIDC
    # (même approche que tests/routes/test_plugins.py).
    from fastapi import FastAPI

    from portal.auth.rbac import UserInfo, require_user
    from portal.db.engine import get_conn
    from portal.routes.mcp import router as mcp_router

    await db_conn.execute(insert(users).values(login="alice", version="1", secret_ns="ns-alice"))

    app = FastAPI()
    app.include_router(mcp_router, prefix="/me")
    app.dependency_overrides[require_user] = lambda: UserInfo(login="alice", roles=["dev"])
    app.dependency_overrides[get_conn] = lambda: db_conn

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_backend_create_list_delete(client: AsyncClient) -> None:
    r = await client.post("/me/mcp/backends", json={
        "namespace": "rag", "name": "RAG", "url": "https://rag/mcp", "transport": "streamable_http",
    })
    assert r.status_code == 201
    bid = r.json()["id"]

    r = await client.get("/me/mcp/backends")
    assert r.status_code == 200 and len(r.json()) == 1

    # namespace dupliqué → 409
    r = await client.post("/me/mcp/backends", json={
        "namespace": "rag", "name": "X", "url": "https://x/mcp", "transport": "sse",
    })
    assert r.status_code == 409

    # namespace avec '__' → 422
    r = await client.post("/me/mcp/backends", json={
        "namespace": "a__b", "name": "X", "url": "https://x/mcp", "transport": "sse",
    })
    assert r.status_code == 422

    r = await client.delete(f"/me/mcp/backends/{bid}")
    assert r.status_code == 204


async def test_apikey_create_returns_clear_once(client: AsyncClient) -> None:
    r = await client.post("/me/mcp/apikeys", json={"label": "cli"})
    assert r.status_code == 201
    body = r.json()
    assert body["token"].startswith("mcpk_")
    # le listing ne ré-expose jamais le clair ni le hash
    r = await client.get("/me/mcp/apikeys")
    assert r.status_code == 200
    assert "token" not in r.json()[0] and "token_hash" not in r.json()[0]


async def test_grant_key_must_belong_to_backend(client: AsyncClient, db_conn: AsyncConnection) -> None:
    b1 = (await client.post("/me/mcp/backends", json={
        "namespace": "rag", "name": "RAG", "url": "https://rag/mcp", "transport": "streamable_http"})).json()["id"]
    b2 = (await client.post("/me/mcp/backends", json={
        "namespace": "wf", "name": "WF", "url": "https://wf/mcp", "transport": "streamable_http"})).json()["id"]
    # clé insérée directement en DB (évite la dépendance vault dans un test route)
    await insert_backend_key(
        db_conn, id="kB2", backend_id=b2, slug="read", description="",
        storage_type="local", secret_value_local=b"x", secret_value_vault_ref=None, vault_identifier=None,
    )
    aid = (await client.post("/me/mcp/apikeys", json={"label": "cli"})).json()["id"]

    # clé de b2 affectée à un grant sur b1 → 422
    r = await client.put(f"/me/mcp/apikeys/{aid}/grants", json={"backend_id": b1, "backend_key_id": "kB2"})
    assert r.status_code == 422
```

> **Vérification préalable** : confirmer dans `tests/routes/test_plugins.py` (lignes ~60-75) le pattern exact `ASGITransport`/`AsyncClient` et l'import `get_conn` depuis `portal.db.engine`. Aligner si la signature diffère. La fixture `db_conn` provient de `tests/conftest.py` (testcontainer) ; le test skip automatiquement si Docker est absent.

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `cd backend && uv run pytest tests/routes/test_mcp_routes.py -v`
Expected: FAIL (404 partout, routeur absent).

- [ ] **Step 3 : Écrire `routes/mcp.py`**

```python
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Request
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..db import mcp as db
from ..db.engine import get_conn
from ..mcp import models, service

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["mcp"])

_ID = Path(..., pattern=r"^[a-z0-9]{1,64}$")


def _sid(request: Request) -> str:
    return str(request.session.get("session_id", ""))


def _map_error(exc: Exception) -> None:
    if isinstance(exc, service.NamespaceTaken):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, service.VaultLocked):
        raise HTTPException(status_code=403, detail="vault_locked") from exc
    if isinstance(exc, service.NotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, service.InvalidReference):
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ─── Backends ─────────────────────────────────────────────────────────────────

@router.get("/mcp/backends")
async def list_backends_route(
    user: UserInfo = Depends(require_user), conn: AsyncConnection = Depends(get_conn)
) -> list[dict[str, Any]]:
    return await db.list_backends(conn, user.login)


@router.post("/mcp/backends", status_code=201)
async def create_backend_route(
    body: models.BackendCreate,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        bid = await service.create_backend(conn, user.login, body)
    except Exception as exc:
        _map_error(exc)
        raise
    return {"id": bid}


@router.patch("/mcp/backends/{backend_id}")
async def update_backend_route(
    body: models.BackendUpdate,
    backend_id: str = _ID,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    ok = await db.update_backend(
        conn, user.login, backend_id,
        name=body.name, url=body.url, transport=body.transport, enabled=body.enabled,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="backend introuvable")
    return {"id": backend_id}


@router.delete("/mcp/backends/{backend_id}", status_code=204)
async def delete_backend_route(
    backend_id: str = _ID,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    if not await db.delete_backend(conn, user.login, backend_id):
        raise HTTPException(status_code=404, detail="backend introuvable")


# ─── Clés de service ──────────────────────────────────────────────────────────

@router.get("/mcp/backends/{backend_id}/keys")
async def list_keys_route(
    backend_id: str = _ID,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    if await db.get_backend(conn, user.login, backend_id) is None:
        raise HTTPException(status_code=404, detail="backend introuvable")
    return await db.list_backend_keys(conn, backend_id)


@router.post("/mcp/backends/{backend_id}/keys", status_code=201)
async def create_key_route(
    body: models.KeyCreate,
    request: Request,
    backend_id: str = _ID,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        kid = await service.create_backend_key(conn, user.login, backend_id, _sid(request), body)
    except Exception as exc:
        _map_error(exc)
        raise
    return {"id": kid}


@router.delete("/mcp/backends/{backend_id}/keys/{key_id}", status_code=204)
async def delete_key_route(
    backend_id: str = _ID,
    key_id: str = Path(..., pattern=r"^[a-z0-9]{1,64}$"),
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    if await db.get_backend(conn, user.login, backend_id) is None:
        raise HTTPException(status_code=404, detail="backend introuvable")
    if not await db.delete_backend_key(conn, backend_id, key_id):
        raise HTTPException(status_code=404, detail="clé introuvable")


# ─── Apikeys clients ──────────────────────────────────────────────────────────

@router.get("/mcp/apikeys")
async def list_apikeys_route(
    user: UserInfo = Depends(require_user), conn: AsyncConnection = Depends(get_conn)
) -> list[dict[str, Any]]:
    return await db.list_apikeys(conn, user.login)


@router.post("/mcp/apikeys", status_code=201)
async def create_apikey_route(
    body: models.ApikeyCreate,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    aid, clear = await service.create_apikey(conn, user.login, body)
    return {"id": aid, "token": clear}


@router.post("/mcp/apikeys/{apikey_id}/revoke")
async def revoke_apikey_route(
    apikey_id: str = _ID,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    if not await db.revoke_apikey(conn, user.login, apikey_id):
        raise HTTPException(status_code=404, detail="apikey introuvable")
    return {"id": apikey_id}


@router.delete("/mcp/apikeys/{apikey_id}", status_code=204)
async def delete_apikey_route(
    apikey_id: str = _ID,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    if not await db.delete_apikey(conn, user.login, apikey_id):
        raise HTTPException(status_code=404, detail="apikey introuvable")


# ─── Grants ───────────────────────────────────────────────────────────────────

@router.get("/mcp/apikeys/{apikey_id}/grants")
async def list_grants_route(
    apikey_id: str = _ID,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    rows = await db.list_apikeys(conn, user.login)
    if not any(r["id"] == apikey_id for r in rows):
        raise HTTPException(status_code=404, detail="apikey introuvable")
    return await db.list_grants(conn, apikey_id)


@router.put("/mcp/apikeys/{apikey_id}/grants")
async def set_grant_route(
    body: models.GrantSet,
    apikey_id: str = _ID,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        await service.set_grant(conn, user.login, apikey_id, body)
    except Exception as exc:
        _map_error(exc)
        raise
    return {"apikey_id": apikey_id, "backend_id": body.backend_id}


@router.delete("/mcp/apikeys/{apikey_id}/grants/{backend_id}", status_code=204)
async def delete_grant_route(
    apikey_id: str = _ID,
    backend_id: str = Path(..., pattern=r"^[a-z0-9]{1,64}$"),
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    rows = await db.list_apikeys(conn, user.login)
    if not any(r["id"] == apikey_id for r in rows):
        raise HTTPException(status_code=404, detail="apikey introuvable")
    if not await db.delete_grant(conn, apikey_id, backend_id):
        raise HTTPException(status_code=404, detail="grant introuvable")
```

> Note : les `id` générés par `new_id()` (uuid4 hex) sont `[a-f0-9]{32}`, compatibles avec le pattern `^[a-z0-9]{1,64}$` des paramètres de chemin.

- [ ] **Step 4 : Enregistrer le routeur dans `app.py`**

Dans `backend/src/portal/app.py`, ajouter l'import près des autres routes :

```python
from .routes.mcp import router as mcp_router
```

Et l'enregistrement, à côté des autres `app.include_router(..., prefix="/me")` :

```python
    app.include_router(mcp_router, prefix="/me")
```

- [ ] **Step 5 : Lancer les tests routes, vérifier le succès**

Run: `cd backend && uv run pytest tests/routes/test_mcp_routes.py -v`
Expected: tous PASS.

- [ ] **Step 6 : Suite complète + lint + mypy**

Run:
```bash
cd backend && uv run pytest tests/db/test_mcp.py tests/mcp/ tests/secrets/test_resolver_protocol.py tests/routes/test_mcp_routes.py -v
uv run ruff check src/portal/routes/mcp.py src/portal/app.py && uv run mypy src/portal/mcp/ src/portal/routes/mcp.py src/portal/db/mcp.py
```
Expected: tout vert.

- [ ] **Step 7 : Commit**

```bash
cd .. && git add backend/src/portal/routes/mcp.py backend/src/portal/app.py backend/tests/routes/test_mcp_routes.py
git commit -m "feat(mcp): routes /me/mcp (backends, clés, apikeys, grants) + montage app"
```

---

## Self-Review

**1. Couverture spec (lot 1 tel que cadré par l'utilisateur) :**
- Enregistrement des backends MCP → Tasks 1,2,5,8 ✓
- Clés de service 1..N par backend, slug unique → Tasks 1,3,6,8 (UNIQUE backend_id+slug) ✓
- Stockage cohérent onglet Secrets (local chiffré / wallet référence) → Task 6 ✓
- « Jamais de secret en clair en base » → Task 6 (chiffrement local), `_KEY_COLS` n'expose pas `secret_value_local` (Task 3) ✓
- Apikey client → ensemble de services avec sélection de la clé → Tasks 1,3,7,8 (grants, PK apikey+backend, garde-fou clé↔backend) ✓
- Valeur claire d'apikey montrée une seule fois → Task 7/8 (POST retourne `token`, listing jamais) ✓
- SecretResolver Protocol + EnvSecretResolver → Task 4 ✓
- Scope par utilisateur → `owner_login` + `/me` + isolation testée (Tasks 2,6,7) ✓
- Hors lot 1 (catalogue, audit, runtime MCP) → non couvert volontairement ✓

**2. Placeholders :** aucun « TBD/TODO ». Deux notes « vérification préalable » (helpers `vault.session`, fixture `client`) sont des points de confirmation contre le code réel, pas des trous — l'implémenteur lit le fichier cité et reprend les noms exacts.

**3. Cohérence des types :** `new_id`, `token_hash`, `create_backend`, `create_backend_key`, `create_apikey`, `set_grant`, et les fonctions `db.mcp` portent des signatures identiques entre les blocs Interfaces, l'implémentation et les tests. Les noms de colonnes (`secret_value_local`, `token_hash`, `backend_key_id`) sont constants partout.

**Point de vigilance reporté (hors lot 1)** : une clé `storage_type='local'` est chiffrée avec la master_key de session de l'owner. Le serveur MCP runtime (lot ultérieur) devra résoudre l'accès à ce secret sans session interactive — à traiter dans le lot serveur frontal, pas ici.
