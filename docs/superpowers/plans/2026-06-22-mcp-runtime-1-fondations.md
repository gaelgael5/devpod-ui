# MCP Runtime — Plan 1 : Fondations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Poser les fondations du runtime de fédération MCP : dépendance SDK `mcp`, chiffrement KEK système des clés de service (résoluble sans session vault), tables `mcp_tool_catalog`/`mcp_audit_log` + curation par grant, et un `RuntimeSecretResolver` qui résout la clé d'un grant en valeur claire.

**Architecture:** Étend le module `portal/mcp/` (lot 1). Les clés `local` passent du chiffrement master_key-PIN au chiffrement KEK système (`PORTAL_VAULT_KEK`), pour que la passerelle déchiffre en autonomie au runtime. Deux nouvelles tables (catalogue + audit) et des colonnes de curation sur les grants. Aucun composant MCP réseau dans ce plan (plans 2-4).

**Tech Stack:** Python 3.12, SQLAlchemy Core (asyncpg), pydantic v2, Alembic, cryptography (AES-GCM + HKDF via `vault/crypto.py`), SDK `mcp`, pytest + testcontainers.

**Spec:** `docs/superpowers/specs/2026-06-22-mcp-runtime-design.md` (§5, §6, §7, §12).

## Global Constraints

- Branche `dev` exclusivement ; commits conventionnels en français.
- `from __future__ import annotations` en tête de chaque fichier ; type hints partout.
- pydantic v2 `extra="forbid"` ; SQLAlchemy Core (pas asyncpg brut) ; tables dans `db/tables.py` ; migration Alembic numérotée **018** (down_revision **017**).
- Fichiers ≤ 300 lignes ; logs structlog, jamais de secret en clair ; type `Secret` déballé seulement via `.reveal()`.
- Scope par utilisateur ; KEK système = `settings.portal_vault_kek` (hex 32 octets).
- TDD : test rouge → impl → test vert → commit. Tests DB via fixture `db_conn` (testcontainer) — **SKIP en local (Docker absent)**, validés sur CI `test.yml`. Les tests **purs** (KEK, resolver) tournent en local et doivent être verts.
- Validation locale obligatoire par tâche : `uv run ruff check <fichiers>`, `uv run mypy <fichiers src>`, et `uv run pytest <tests> -v` (documenter SKIP DB). Sortie de test **pristine** (0 warning) ; pas de `pytestmark` redondant (projet en `asyncio_mode=auto`).

---

## File Structure

| Fichier | Responsabilité |
|---|---|
| `backend/pyproject.toml` (modif) | Ajout dépendance `mcp` |
| `backend/src/portal/mcp/runtime_secrets.py` (créer) | KEK système (chiffre/déchiffre `local`) + `RuntimeSecretResolver` (local/none/env) |
| `backend/src/portal/mcp/service.py` (modif) | `create_backend_key` local → KEK système (retire la dépendance `session_id` pour `local`) |
| `backend/src/portal/db/tables.py` (modif) | Tables `mcp_tool_catalog`, `mcp_audit_log` ; colonnes `expose_mode`/`expose` sur `mcp_apikey_grant` |
| `backend/alembic/versions/018_mcp_runtime.py` (créer) | Migration des 2 tables + 2 colonnes |
| `backend/src/portal/db/mcp_catalog.py` (créer) | CRUD `mcp_tool_catalog` |
| `backend/src/portal/db/mcp_audit.py` (créer) | Insert/list `mcp_audit_log` |
| `backend/src/portal/db/mcp.py` (modif) | `set_grant`/`list_grants` portent la curation (`expose_mode`/`expose`) |
| `backend/src/portal/mcp/models.py` (modif) | `GrantSet` porte `expose_mode`/`expose` |
| Tests : `tests/mcp/test_runtime_secrets.py`, `tests/db/test_mcp_catalog.py`, `tests/db/test_mcp_audit.py`, ajouts à `tests/db/test_mcp.py`, `tests/mcp/test_service.py` | |

---

## Task 1 : Dépendance SDK `mcp`

**Files:**
- Modify: `backend/pyproject.toml`

**Interfaces:**
- Produces: le paquet `mcp` importable dans l'environnement (utilisé par les plans 2-4).

- [ ] **Step 1 : Ajouter la dépendance**

Run: `cd backend && uv add "mcp>=1.8"`
(Met à jour `pyproject.toml` + `uv.lock`.)

- [ ] **Step 2 : Vérifier l'import**

Run: `cd backend && uv run python -c "import mcp; from mcp.client.streamable_http import streamablehttp_client; print('mcp ok')"`
Expected: `mcp ok` (si le chemin d'import diffère selon la version, ajuster — l'objectif est de confirmer que le client Streamable HTTP est disponible ; documenter le chemin réel dans le rapport pour les plans suivants).

- [ ] **Step 3 : Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "build(mcp): ajoute la dépendance SDK mcp pour le runtime de fédération"
```

---

## Task 2 : KEK système — primitives de chiffrement

**Files:**
- Create: `backend/src/portal/mcp/runtime_secrets.py`
- Test: `backend/tests/mcp/test_runtime_secrets.py`

**Interfaces:**
- Consumes: `vault.crypto.encrypt_token`/`decrypt_token`, `settings.get_settings().portal_vault_kek`.
- Produces:
  - `class KekUnavailable(Exception)`
  - `def encrypt_service_key(plaintext: str) -> bytes` — chiffre avec la KEK système dérivée
  - `def decrypt_service_key(blob: bytes) -> str` — déchiffre
  - `def _derive_kek() -> bytes` (interne, 32 octets)

- [ ] **Step 1 : Écrire les tests purs (pas de DB)**

Créer `backend/tests/mcp/test_runtime_secrets.py` :

```python
from __future__ import annotations

import pytest

from portal.mcp import runtime_secrets


def test_encrypt_decrypt_roundtrip(monkeypatch) -> None:
    monkeypatch.setattr(
        "portal.settings.get_settings",
        lambda: type("S", (), {"portal_vault_kek": "11" * 32})(),
    )
    blob = runtime_secrets.encrypt_service_key("rag-token-123")
    assert isinstance(blob, bytes)
    assert blob != b"rag-token-123"
    assert runtime_secrets.decrypt_service_key(blob) == "rag-token-123"


def test_missing_kek_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        "portal.settings.get_settings",
        lambda: type("S", (), {"portal_vault_kek": ""})(),
    )
    with pytest.raises(runtime_secrets.KekUnavailable):
        runtime_secrets.encrypt_service_key("x")
```

> Vérification : confirmer dans `portal/settings.py` le nom de l'accès aux settings (`get_settings()`) et l'attribut `portal_vault_kek`. Adapter le monkeypatch si l'API réelle diffère.

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `cd backend && uv run pytest tests/mcp/test_runtime_secrets.py -v`
Expected: FAIL (`ModuleNotFoundError` / attributs absents).

- [ ] **Step 3 : Implémenter `runtime_secrets.py` (primitives)**

```python
from __future__ import annotations

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..settings import get_settings
from ..vault.crypto import decrypt_token, encrypt_token


class KekUnavailable(Exception):
    """PORTAL_VAULT_KEK absent : impossible de chiffrer/déchiffrer une clé de service."""


def _derive_kek() -> bytes:
    kek_hex = get_settings().portal_vault_kek
    if not kek_hex:
        raise KekUnavailable("PORTAL_VAULT_KEK non configuré")
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"mcp-backend-key-v1",
    )
    return hkdf.derive(bytes.fromhex(kek_hex))


def encrypt_service_key(plaintext: str) -> bytes:
    return encrypt_token(plaintext, _derive_kek())


def decrypt_service_key(blob: bytes) -> str:
    return decrypt_token(blob, _derive_kek())
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run: `cd backend && uv run pytest tests/mcp/test_runtime_secrets.py -v`
Expected: 2 passed, 0 warning.

- [ ] **Step 5 : Lint + commit**

```bash
cd backend && uv run ruff check src/portal/mcp/runtime_secrets.py tests/mcp/test_runtime_secrets.py && uv run mypy src/portal/mcp/runtime_secrets.py
cd .. && git add backend/src/portal/mcp/runtime_secrets.py backend/tests/mcp/test_runtime_secrets.py
git commit -m "feat(mcp): KEK système pour chiffrer les clés de service (runtime autonome)"
```

---

## Task 3 : `create_backend_key` (local) → KEK système

**Files:**
- Modify: `backend/src/portal/mcp/service.py`
- Test: `backend/tests/mcp/test_service.py` (ajustement)

**Interfaces:**
- Consumes: `runtime_secrets.encrypt_service_key`.
- Produces: `create_backend_key` chiffre le `local` avec la KEK système ; **ne lève plus `VaultLocked` pour `local`** (plus de dépendance `session_id` pour ce mode). `harpocrate` reste inchangé (dépend de `session_id`).

- [ ] **Step 1 : Lire l'implémentation actuelle**

Lire `create_backend_key` dans `src/portal/mcp/service.py` (branche `local` : `master_key = vault_session.get_master_key(session_id)` → `VaultLocked` si None → `encrypt_token(secret_value, master_key)`).

- [ ] **Step 2 : Adapter le test du chiffrement local**

Dans `tests/mcp/test_service.py`, le test `test_create_local_key_encrypts_value` déverrouille le vault et vérifie `decrypt_token(blob, mk)`. Le remplacer pour vérifier le chiffrement KEK (sans session) :

```python
async def test_create_local_key_encrypts_with_kek(db_conn, monkeypatch) -> None:
    monkeypatch.setattr(
        "portal.settings.get_settings",
        lambda: type("S", (), {"portal_vault_kek": "22" * 32})(),
    )
    await _user(db_conn)
    bid = await service.create_backend(
        db_conn, "alice",
        models.BackendCreate(namespace="rag", name="RAG", url="https://rag/mcp", transport="streamable_http"),
    )
    key_body = models.KeyCreate(
        slug="read", description="ro", storage_type="local",
        secret_value="rag-token-123", vault_identifier=None,
    )
    # plus besoin de session vault pour 'local'
    kid = await service.create_backend_key(db_conn, "alice", bid, "no-session", key_body)

    from portal.db.tables import mcp_backend_key
    from portal.mcp.runtime_secrets import decrypt_service_key
    from sqlalchemy import select
    blob = (
        await db_conn.execute(
            select(mcp_backend_key.c.secret_value_local).where(mcp_backend_key.c.id == kid)
        )
    ).scalar_one()
    assert blob != b"rag-token-123"
    assert decrypt_service_key(blob) == "rag-token-123"
```

Supprimer l'ancien `test_create_local_key_encrypts_value` et `test_create_local_key_requires_unlocked_vault` (le `local` ne requiert plus de vault). Conserver les tests harpocrate et `test_create_key_on_foreign_backend_denied` (le backend d'autrui → `NotFound`, indépendant du vault).

- [ ] **Step 3 : Lancer, vérifier l'échec**

Run: `cd backend && uv run pytest tests/mcp/test_service.py -k "kek" -v`
Expected: FAIL (le code chiffre encore avec master_key et lève VaultLocked sur "no-session").

- [ ] **Step 4 : Modifier la branche `local` de `create_backend_key`**

Remplacer la branche `local` :

```python
    if body.storage_type == "local":
        # Clé de service chiffrée avec la KEK système : la passerelle la
        # déchiffre en autonomie au runtime, sans session vault de l'owner.
        local_blob = encrypt_service_key(body.secret_value)
    else:  # harpocrate : valeur poussée dans le wallet (dépend de la session)
        ...
```

Import à ajouter en tête : `from .runtime_secrets import encrypt_service_key`. Retirer l'usage de `vault_session.get_master_key`/`encrypt_token` pour la branche `local` (les garder si `harpocrate` en a besoin — il ne les utilise pas ; `harpocrate` utilise `get_vault_client`). Supprimer la garde `VaultLocked` du chemin `local` ; `VaultLocked` reste levé dans la branche `harpocrate` (vault déverrouillé requis pour pousser au wallet).

- [ ] **Step 5 : Lancer la suite service, vérifier le succès**

Run: `cd backend && uv run pytest tests/mcp/test_service.py -v`
Expected: tests pydantic verts ; tests DB SKIP en local (le test KEK skip aussi car `db_conn`). 0 warning. (Validation réelle sur CI Docker.)

- [ ] **Step 6 : Lint + mypy + commit**

```bash
cd backend && uv run ruff check src/portal/mcp/service.py tests/mcp/test_service.py && uv run mypy src/portal/mcp/service.py
cd .. && git add backend/src/portal/mcp/service.py backend/tests/mcp/test_service.py
git commit -m "feat(mcp): clés 'local' chiffrées via KEK système (plus de dépendance session)"
```

---

## Task 4 : Migration 018 — tables catalogue/audit + curation

**Files:**
- Modify: `backend/src/portal/db/tables.py`
- Create: `backend/alembic/versions/018_mcp_runtime.py`
- Test: `backend/tests/db/test_mcp_catalog.py` (smoke des tables)

**Interfaces:**
- Produces: tables `mcp_tool_catalog`, `mcp_audit_log` ; colonnes `expose_mode` (Text, default `'all'`), `expose` (JSONB, default `[]`) sur `mcp_apikey_grant`.

- [ ] **Step 1 : Écrire le smoke test des tables**

Créer `backend/tests/db/test_mcp_catalog.py` :

```python
from __future__ import annotations

import uuid

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.tables import mcp_apikey_grant, mcp_audit_log, mcp_backend, mcp_tool_catalog, users


async def _seed_backend(conn: AsyncConnection) -> None:
    await conn.execute(insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4())))
    await conn.execute(
        insert(mcp_backend).values(
            id="b1", owner_login="alice", namespace="rag", name="RAG",
            url="https://rag/mcp", transport="streamable_http",
        )
    )


async def test_catalog_and_audit_smoke(db_conn: AsyncConnection) -> None:
    await _seed_backend(db_conn)
    await db_conn.execute(
        insert(mcp_tool_catalog).values(
            backend_id="b1", kind="tool", original_name="search",
            definition={"name": "search"}, definition_hash="h",
        )
    )
    await db_conn.execute(
        insert(mcp_audit_log).values(status="ok", owner_login="alice", backend_id="b1")
    )
    rows = (await db_conn.execute(select(mcp_tool_catalog.c.original_name))).all()
    assert rows == [("search",)]


async def test_grant_curation_defaults(db_conn: AsyncConnection) -> None:
    await _seed_backend(db_conn)
    await db_conn.execute(insert(mcp_apikey_grant).values(apikey_id="a1", backend_id="b1"))
    # NB: a1 n'existe pas en mcp_apikey ici → ce test vérifie seulement les defaults
    #     de colonnes ; il insère donc sans FK apikey valide est impossible.
```

> Le second test est un placeholder conceptuel : la FK `apikey_id` impose une apikey valide. Le remplacer par une vérification des defaults via `mcp_apikey` réel (insérer une apikey, un grant, lire `expose_mode`='all', `expose`=[]). L'implémenteur écrit la version correcte (créer `mcp_apikey` puis le grant, asserter les defaults).

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `cd backend && uv run pytest tests/db/test_mcp_catalog.py::test_catalog_and_audit_smoke -v`
Expected: FAIL (`ImportError` sur `mcp_tool_catalog`/`mcp_audit_log`).

- [ ] **Step 3 : Déclarer les tables dans `tables.py`**

Ajouter (imports `Integer`, `JSONB` déjà présents ; sinon compléter) en fin de section MCP :

```python
mcp_tool_catalog = Table(
    "mcp_tool_catalog",
    metadata,
    Column("backend_id", Text, ForeignKey("mcp_backend.id", ondelete="CASCADE"), nullable=False),
    Column("kind", Text, nullable=False),  # 'tool' | 'resource' | 'prompt'
    Column("original_name", Text, nullable=False),
    Column("definition", JSONB, nullable=False),
    Column("definition_hash", Text, nullable=False),
    Column("first_seen", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_seen", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("quarantined", Boolean, nullable=False, server_default="false"),
    UniqueConstraint("backend_id", "kind", "original_name", name="pk_mcp_tool_catalog"),
)

mcp_audit_log = Table(
    "mcp_audit_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("apikey_id", Text, nullable=True),
    Column("owner_login", Text, nullable=True),
    Column("namespaced_name", Text, nullable=True),
    Column("backend_id", Text, nullable=True),
    Column("backend_key_id", Text, nullable=True),
    Column("latency_ms", Integer, nullable=True),
    Column("status", Text, nullable=False),  # ok | error | denied | timeout
    Column("error", Text, nullable=True),
)
```

Et ajouter à `mcp_apikey_grant` (après `backend_key_id`) :

```python
    Column("expose_mode", Text, nullable=False, server_default="all"),  # all | allowlist | denylist
    Column("expose", JSONB, nullable=False, server_default="[]"),
```

> `mcp_audit_log` : pas de FK (conservation après suppression). `pk_mcp_tool_catalog` est une UniqueConstraint nommée (PK logique composite ; cohérent avec le style du fichier).

- [ ] **Step 4 : Écrire la migration `018_mcp_runtime.py`**

```python
"""mcp runtime : catalogue, audit, curation par grant.

Revision ID: 018
Revises: 017
Create Date: 2026-06-22
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "018"
down_revision: str | None = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_tool_catalog",
        sa.Column("backend_id", sa.Text(), sa.ForeignKey("mcp_backend.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("original_name", sa.Text(), nullable=False),
        sa.Column("definition", JSONB(), nullable=False),
        sa.Column("definition_hash", sa.Text(), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("quarantined", sa.Boolean(), nullable=False, server_default="false"),
        sa.UniqueConstraint("backend_id", "kind", "original_name", name="pk_mcp_tool_catalog"),
    )
    op.create_table(
        "mcp_audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("apikey_id", sa.Text(), nullable=True),
        sa.Column("owner_login", sa.Text(), nullable=True),
        sa.Column("namespaced_name", sa.Text(), nullable=True),
        sa.Column("backend_id", sa.Text(), nullable=True),
        sa.Column("backend_key_id", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.add_column(
        "mcp_apikey_grant",
        sa.Column("expose_mode", sa.Text(), nullable=False, server_default="all"),
    )
    op.add_column(
        "mcp_apikey_grant",
        sa.Column("expose", JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("mcp_apikey_grant", "expose")
    op.drop_column("mcp_apikey_grant", "expose_mode")
    op.drop_table("mcp_audit_log")
    op.drop_table("mcp_tool_catalog")
```

- [ ] **Step 5 : Réécrire le 2e test proprement + lancer**

Remplacer le placeholder `test_grant_curation_defaults` par une version correcte (insérer `mcp_apikey` puis le grant, asserter `expose_mode`='all', `expose`==[]). Puis :

Run: `cd backend && uv run pytest tests/db/test_mcp_catalog.py -v`
Expected: SKIP en local (Docker). Vérifier ruff/mypy.

- [ ] **Step 6 : Lint + commit**

```bash
cd backend && uv run ruff check src/portal/db/tables.py alembic/versions/018_mcp_runtime.py tests/db/test_mcp_catalog.py && uv run mypy src/portal/db/tables.py
cd .. && git add backend/src/portal/db/tables.py backend/alembic/versions/018_mcp_runtime.py backend/tests/db/test_mcp_catalog.py
git commit -m "feat(mcp): migration 018 — catalogue, audit, curation par grant"
```

---

## Task 5 : Couches DB catalogue & audit + curation dans les grants

**Files:**
- Create: `backend/src/portal/db/mcp_catalog.py`, `backend/src/portal/db/mcp_audit.py`
- Modify: `backend/src/portal/db/mcp.py` (set_grant/list_grants portent la curation), `backend/src/portal/mcp/models.py` (GrantSet)
- Test: `backend/tests/db/test_mcp_catalog.py`, `backend/tests/db/test_mcp_audit.py`, ajout à `tests/db/test_mcp.py`

**Interfaces:**
- Produces:
  - `mcp_catalog.upsert_primitive(conn, *, backend_id, kind, original_name, definition: dict, definition_hash: str) -> bool` (retourne `quarantined` après upsert : True si hash changé vs existant non-quarantiné)
  - `mcp_catalog.list_primitives(conn, backend_id: str, kind: str) -> list[dict]`
  - `mcp_catalog.set_quarantine(conn, backend_id, kind, original_name, value: bool) -> None`
  - `mcp_catalog.prune_absent(conn, backend_id, kind, present_names: list[str]) -> None`
  - `mcp_audit.record(conn, *, apikey_id, owner_login, namespaced_name, backend_id, backend_key_id, latency_ms, status, error) -> None`
  - `mcp_audit.list_for_owner(conn, owner_login, limit=100) -> list[dict]`
  - `db.mcp.set_grant(...)` accepte `expose_mode: str` et `expose: list[str]` ; `list_grants` les retourne.
  - `models.GrantSet` : `expose_mode: Literal["all","allowlist","denylist"]="all"`, `expose: list[str]=[]`.

- [ ] **Step 1 : Écrire les tests (catalogue upsert/quarantaine, audit, curation grant)**

Ajouter à `tests/db/test_mcp_catalog.py` un test `test_upsert_detects_rugpull` :

```python
from portal.db.mcp_catalog import list_primitives, set_quarantine, upsert_primitive


async def test_upsert_detects_rugpull(db_conn: AsyncConnection) -> None:
    await _seed_backend(db_conn)
    q1 = await upsert_primitive(
        db_conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "search", "v": 1}, definition_hash="h1",
    )
    assert q1 is False  # première vue, pas de quarantaine
    # redéfinition (hash différent) → quarantaine
    q2 = await upsert_primitive(
        db_conn, backend_id="b1", kind="tool", original_name="search",
        definition={"name": "search", "v": 2}, definition_hash="h2",
    )
    assert q2 is True
    rows = await list_primitives(db_conn, "b1", "tool")
    assert rows[0]["quarantined"] is True
    await set_quarantine(db_conn, "b1", "tool", "search", False)
    rows = await list_primitives(db_conn, "b1", "tool")
    assert rows[0]["quarantined"] is False
```

Créer `tests/db/test_mcp_audit.py` :

```python
from __future__ import annotations

import uuid

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp_audit import list_for_owner, record
from portal.db.tables import users


async def test_audit_record_and_list(db_conn: AsyncConnection) -> None:
    await db_conn.execute(insert(users).values(login="alice", version="1", secret_ns=str(uuid.uuid4())))
    await record(
        db_conn, apikey_id="a1", owner_login="alice", namespaced_name="rag__search",
        backend_id="b1", backend_key_id="k1", latency_ms=42, status="ok", error=None,
    )
    rows = await list_for_owner(db_conn, "alice")
    assert len(rows) == 1 and rows[0]["status"] == "ok" and rows[0]["namespaced_name"] == "rag__search"
```

Ajouter à `tests/mcp/test_service.py` un test que `set_grant` stocke la curation (allowlist + expose), via `list_grants`.

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `cd backend && uv run pytest tests/db/test_mcp_catalog.py tests/db/test_mcp_audit.py -v`
Expected: FAIL (modules absents).

- [ ] **Step 3 : Implémenter `db/mcp_catalog.py`**

```python
from __future__ import annotations

from typing import Any

from sqlalchemy import and_, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import mcp_tool_catalog as cat

_COLS = [
    cat.c.backend_id, cat.c.kind, cat.c.original_name,
    cat.c.definition, cat.c.definition_hash,
    cat.c.first_seen, cat.c.last_seen, cat.c.quarantined,
]


async def upsert_primitive(
    conn: AsyncConnection, *, backend_id: str, kind: str, original_name: str,
    definition: dict[str, Any], definition_hash: str,
) -> bool:
    """Insère/maj une primitive. Retourne True si une redéfinition est détectée
    (hash différent d'une entrée existante) → mise en quarantaine."""
    from sqlalchemy import func as _func

    existing = (
        await conn.execute(
            select(cat.c.definition_hash, cat.c.quarantined).where(
                cat.c.backend_id == backend_id, cat.c.kind == kind, cat.c.original_name == original_name
            )
        )
    ).first()

    quarantine = existing is not None and existing[0] != definition_hash

    stmt = pg_insert(cat).values(
        backend_id=backend_id, kind=kind, original_name=original_name,
        definition=definition, definition_hash=definition_hash,
        quarantined=quarantine,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="pk_mcp_tool_catalog",
        set_={
            "definition": definition,
            "definition_hash": definition_hash,
            "last_seen": _func.now(),
            # quarantaine collante : on ne lève jamais la quarantaine automatiquement
            "quarantined": cat.c.quarantined | quarantine,
        },
    )
    await conn.execute(stmt)
    return quarantine


async def list_primitives(conn: AsyncConnection, backend_id: str, kind: str) -> list[dict[str, Any]]:
    q = select(*_COLS).where(cat.c.backend_id == backend_id, cat.c.kind == kind).order_by(cat.c.original_name)
    return [dict(r) for r in (await conn.execute(q)).mappings().all()]


async def set_quarantine(
    conn: AsyncConnection, backend_id: str, kind: str, original_name: str, value: bool
) -> None:
    from sqlalchemy import update

    await conn.execute(
        update(cat)
        .where(cat.c.backend_id == backend_id, cat.c.kind == kind, cat.c.original_name == original_name)
        .values(quarantined=value)
    )


async def prune_absent(
    conn: AsyncConnection, backend_id: str, kind: str, present_names: list[str]
) -> None:
    await conn.execute(
        delete(cat).where(
            and_(cat.c.backend_id == backend_id, cat.c.kind == kind, cat.c.original_name.notin_(present_names))
        )
    )
```

> Note : `quarantined = cat.c.quarantined | quarantine` garde la quarantaine collante (une fois quarantiné, reste jusqu'à `set_quarantine(False)` explicite).

- [ ] **Step 4 : Implémenter `db/mcp_audit.py`**

```python
from __future__ import annotations

from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import mcp_audit_log as al


async def record(
    conn: AsyncConnection, *, apikey_id: str | None, owner_login: str | None,
    namespaced_name: str | None, backend_id: str | None, backend_key_id: str | None,
    latency_ms: int | None, status: str, error: str | None,
) -> None:
    await conn.execute(
        insert(al).values(
            apikey_id=apikey_id, owner_login=owner_login, namespaced_name=namespaced_name,
            backend_id=backend_id, backend_key_id=backend_key_id,
            latency_ms=latency_ms, status=status, error=error,
        )
    )


async def list_for_owner(conn: AsyncConnection, owner_login: str, limit: int = 100) -> list[dict[str, Any]]:
    q = (
        select(al)
        .where(al.c.owner_login == owner_login)
        .order_by(al.c.ts.desc())
        .limit(limit)
    )
    return [dict(r) for r in (await conn.execute(q)).mappings().all()]
```

- [ ] **Step 5 : Curation dans `db/mcp.py` + `models.GrantSet`**

`models.py` — `GrantSet` :

```python
class GrantSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend_id: str
    backend_key_id: str | None = None
    expose_mode: Literal["all", "allowlist", "denylist"] = "all"
    expose: list[str] = []
```

`db/mcp.py` — `set_grant` (ajouter les colonnes à l'insert/upsert) et `list_grants` (retourner `expose_mode`/`expose`) :

```python
async def set_grant(
    conn, *, apikey_id, backend_id, backend_key_id, expose_mode="all", expose=None,
):
    expose = expose or []
    stmt = pg_insert(mcp_apikey_grant).values(
        apikey_id=apikey_id, backend_id=backend_id, backend_key_id=backend_key_id,
        expose_mode=expose_mode, expose=expose,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_mcp_apikey_grant_apikey_backend",
        set_={"backend_key_id": backend_key_id, "expose_mode": expose_mode, "expose": expose},
    )
    await conn.execute(stmt)
```

`list_grants` : ajouter `mcp_apikey_grant.c.expose_mode`, `mcp_apikey_grant.c.expose` au `select`.

`service.set_grant` : passer `expose_mode=body.expose_mode, expose=body.expose` à `db.set_grant`.

- [ ] **Step 6 : Lancer la suite (SKIP DB local) + lint + mypy**

Run:
```bash
cd backend && uv run pytest tests/db/test_mcp_catalog.py tests/db/test_mcp_audit.py tests/mcp/test_service.py -v
uv run ruff check src/portal/db/mcp_catalog.py src/portal/db/mcp_audit.py src/portal/db/mcp.py src/portal/mcp/models.py tests/db/test_mcp_catalog.py tests/db/test_mcp_audit.py
uv run mypy src/portal/db/mcp_catalog.py src/portal/db/mcp_audit.py src/portal/db/mcp.py src/portal/mcp/models.py
```
Expected: tests purs verts, DB SKIP, 0 warning ; ruff/mypy OK.

- [ ] **Step 7 : Commit**

```bash
git add backend/src/portal/db/mcp_catalog.py backend/src/portal/db/mcp_audit.py backend/src/portal/db/mcp.py backend/src/portal/mcp/models.py backend/tests/db/test_mcp_catalog.py backend/tests/db/test_mcp_audit.py backend/tests/mcp/test_service.py
git commit -m "feat(mcp): couches DB catalogue/audit + curation (expose_mode/expose) par grant"
```

---

## Task 6 : `RuntimeSecretResolver`

**Files:**
- Modify: `backend/src/portal/mcp/runtime_secrets.py`
- Test: `backend/tests/mcp/test_runtime_secrets.py` (ajout)

**Interfaces:**
- Consumes: `decrypt_service_key`, `secrets.resolver.EnvSecretResolver`, `secrets.types.Secret`.
- Produces:
  - `class UnresolvableSecret(Exception)` (clé harpocrate au runtime, etc.)
  - `async def resolve_grant_key(key_row: dict | None) -> Secret | None` — retourne le bearer en clair (dans `Secret`) pour la clé d'un grant, ou `None` si backend public (`key_row is None`). `key_row` = ligne `mcp_backend_key` (storage_type, secret_value_local, secret_value_vault_ref).

- [ ] **Step 1 : Écrire les tests**

```python
import pytest
from portal.mcp.runtime_secrets import UnresolvableSecret, encrypt_service_key, resolve_grant_key
from portal.secrets.types import Secret

pytestmark_kek = lambda mp: mp.setattr(
    "portal.settings.get_settings", lambda: type("S", (), {"portal_vault_kek": "33" * 32})()
)


async def test_resolve_public_backend_returns_none() -> None:
    assert await resolve_grant_key(None) is None


async def test_resolve_local_key(monkeypatch) -> None:
    pytestmark_kek(monkeypatch)
    blob = encrypt_service_key("tok-abc")
    row = {"storage_type": "local", "secret_value_local": blob, "secret_value_vault_ref": None}
    out = await resolve_grant_key(row)
    assert isinstance(out, Secret) and out.reveal() == "tok-abc"


async def test_resolve_env_ref(monkeypatch) -> None:
    monkeypatch.setenv("MCP_RAG_TOKEN", "env-tok")
    row = {"storage_type": "harpocrate", "secret_value_local": None,
           "secret_value_vault_ref": "${env://MCP_RAG_TOKEN}"}
    out = await resolve_grant_key(row)
    assert out.reveal() == "env-tok"


async def test_resolve_harpocrate_vault_unresolvable() -> None:
    row = {"storage_type": "harpocrate", "secret_value_local": None,
           "secret_value_vault_ref": "${vault://wallet:mcp/b1/read}"}
    with pytest.raises(UnresolvableSecret):
        await resolve_grant_key(row)
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `cd backend && uv run pytest tests/mcp/test_runtime_secrets.py -k "resolve" -v`
Expected: FAIL.

- [ ] **Step 3 : Implémenter `resolve_grant_key`**

Ajouter à `runtime_secrets.py` :

```python
from ..secrets.resolver import EnvSecretResolver, SecretAccessError
from ..secrets.types import Secret


class UnresolvableSecret(Exception):
    """Clé non résoluble au runtime (ex. référence vault/wallet dépendante d'une session)."""


_env_resolver = EnvSecretResolver()


async def resolve_grant_key(key_row: dict | None) -> Secret | None:
    """Résout la clé de service d'un grant en bearer clair.

    None = backend public (aucune clé). Lève UnresolvableSecret pour une
    référence vault (harpocrate) non résoluble sans session.
    """
    if key_row is None:
        return None
    storage = key_row["storage_type"]
    if storage == "local":
        blob = key_row["secret_value_local"]
        if blob is None:
            raise UnresolvableSecret("clé 'local' sans valeur chiffrée")
        return Secret(decrypt_service_key(blob))
    # harpocrate : seule une référence ${env://...} est résoluble au runtime
    ref = key_row.get("secret_value_vault_ref") or ""
    if ref.startswith("${env://"):
        try:
            return await _env_resolver.resolve(ref)
        except SecretAccessError as exc:
            raise UnresolvableSecret(str(exc)) from exc
    raise UnresolvableSecret("référence vault non résoluble au runtime (harpocrate différé)")
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run: `cd backend && uv run pytest tests/mcp/test_runtime_secrets.py -v`
Expected: tous passed, 0 warning.

- [ ] **Step 5 : Lint + mypy + commit**

```bash
cd backend && uv run ruff check src/portal/mcp/runtime_secrets.py tests/mcp/test_runtime_secrets.py && uv run mypy src/portal/mcp/runtime_secrets.py
cd .. && git add backend/src/portal/mcp/runtime_secrets.py backend/tests/mcp/test_runtime_secrets.py
git commit -m "feat(mcp): RuntimeSecretResolver (local-KEK / public / env ; harpocrate différé)"
```

---

## Self-Review

**Couverture spec (Plan 1 = §5, §6, §7, §12 fondations) :**
- KEK système + migration chiffrement local → Tasks 2,3 (§7) ✓
- Tables `mcp_tool_catalog`/`mcp_audit_log` → Task 4 (§5) ✓
- Curation par grant (`expose_mode`/`expose`) → Tasks 4,5 (§12) ✓
- Couches DB catalogue (upsert + quarantaine collante) / audit → Task 5 (§5, §10 rug-pull) ✓
- `RuntimeSecretResolver` (local/none/env ; harpocrate→UnresolvableSecret) → Task 6 (§6) ✓
- SDK `mcp` dispo → Task 1 (§2) ✓
- Hors plan 1 (client, catalogue-sync, agrégation, serveur frontal) → plans 2-4.

**Placeholders :** une note explicite en Task 4 step 1 (2e test placeholder à réécrire) — instruction claire, pas un trou silencieux. Une note de vérification en Task 1 (chemin d'import SDK) et Task 2 (API settings).

**Cohérence des types :** `encrypt_service_key`/`decrypt_service_key`/`resolve_grant_key`, signatures `upsert_primitive`/`record`/`set_grant` identiques entre Interfaces, code et tests. `GrantSet` curation cohérent entre models, db.set_grant, et la migration.

**Point d'attention transmis aux plans suivants :** Task 1 step 2 doit documenter le **chemin d'import réel** du client Streamable HTTP du SDK `mcp` (varie selon version) — requis pour les plans 2-3.
