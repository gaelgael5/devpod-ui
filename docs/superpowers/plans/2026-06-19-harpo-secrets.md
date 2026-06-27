# Harpo Secrets + Edit + Git Credentials — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Table `harpo_secrets` avec onglet UI dédié. (2) Édition (label/description/valeur) pour secrets ET certificats. (3) Alignement Git Credentials : sélectionner un PAT depuis harpo_secrets au lieu de le saisir inline.

**Architecture:**
- `harpo_secrets` suit exactement le même pattern que `harpo_certificates` : valeur unique chiffrée AES-GCM ou stockée dans wallet Harpocrate, uniquement par `(owner_login, slug)`.
- Edition : PATCH endpoint + re-chiffrement local ou `client.secrets.put()` pour harpocrate.
- Git Credentials : quand `kind=token`, l'UI propose un switch "choisir depuis mes secrets PAT_GITHUB" qui remplace la saisie inline.

**Tech Stack:** Python `cryptography`, FastAPI, SQLAlchemy Core async, pydantic v2, React 18 + TanStack Query + shadcn/ui + i18next.

## Global Constraints

- Python 3.12+, `from __future__ import annotations` en tête de chaque fichier Python
- Async/await partout
- pydantic v2, `extra="forbid"` sur tous les modèles
- `structlog.get_logger(__name__)` — jamais `print()`
- Valeur secrète : jamais en clair dans les logs
- Commits en français, format conventionnel (`feat:`, `fix:`, `chore:`…)
- Tests : `pytest-asyncio`, fixture `db_conn`
- Fichiers max 300 lignes, méthodes 5-15 lignes
- Branche `dev` uniquement
- Pas de `detail=str(exc)` dans les handlers d'erreur

---

## Structure des fichiers

### Créés

| Fichier | Responsabilité |
|---|---|
| `backend/alembic/versions/014_harpo_secrets.py` | Migration SQL |
| `backend/src/portal/db/secrets.py` | CRUD bas niveau |
| `backend/src/portal/secrets/__init__.py` | Package marker |
| `backend/src/portal/secrets/service.py` | Logique métier (register, reveal, update, remove) |
| `backend/src/portal/routes/secrets.py` | Endpoints FastAPI `/me/secrets` et `/admin/secrets` |
| `backend/tests/db/test_secrets.py` | Tests CRUD DB |
| `backend/tests/secrets/__init__.py` | Package marker |
| `backend/tests/secrets/test_service.py` | Tests service |
| `frontend/src/features/secrets/api.ts` | Hooks TanStack Query |
| `frontend/src/features/secrets/SecretsTab.tsx` | Composant onglet |

### Modifiés

| Fichier | Changement |
|---|---|
| `backend/src/portal/db/tables.py` | Ajouter table `harpo_secrets` |
| `backend/src/portal/app.py` | Enregistrer routers secrets |
| `backend/src/portal/db/certificates.py` | Ajouter `update_certificate` |
| `backend/src/portal/certificates/service.py` | Ajouter `edit_certificate` |
| `backend/src/portal/routes/certificates.py` | Ajouter PATCH /me/certificates/{slug} |
| `frontend/src/features/certificates/api.ts` | Ajouter `useUpdateCertificate` |
| `frontend/src/features/certificates/CertificatesTab.tsx` | Ajouter dialog Edit |
| `frontend/src/features/git-credentials/CredentialsPage.tsx` | Ajouter onglet Secrets |
| `frontend/src/features/git-credentials/GitCredentialManager.tsx` | Switch PAT inline → picker secrets |
| `frontend/src/features/git-credentials/useGitCredentials.ts` | (si besoin) |
| `frontend/src/i18n/fr.json` | Clés `secrets.*`, `gitCredentials.patPicker.*` |
| `frontend/src/i18n/en.json` | Même |

---

## Tâche 1 — Table harpo_secrets + migration 014

**Fichiers :**
- Modifier : `backend/src/portal/db/tables.py`
- Créer : `backend/alembic/versions/014_harpo_secrets.py`

**Interfaces produites :**
- Table `harpo_secrets` importable comme `from .tables import harpo_secrets`

- [ ] **Étape 1 : Ajouter la table dans `tables.py`**

À la fin de `backend/src/portal/db/tables.py`, ajouter :

```python
# ─── Tour 12 : harpo_secrets ─────────────────────────────────────────────────

harpo_secrets = Table(
    "harpo_secrets",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("slug", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=""),
    # PAT_GITHUB | PAT_GITLAB | PAT_AZURE | API_KEY | … (extensible)
    Column("secret_type", Text, nullable=False),
    Column("secret_value_local", LargeBinary, nullable=True),   # AES-GCM, master_key
    Column("secret_value_vault_ref", Text, nullable=True),       # ${vault://id:secrets/slug/value}
    Column("storage_type", Text, nullable=False),               # local | harpocrate
    Column("vault_identifier", Text, nullable=True),
    Column("owner_login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("is_public", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("owner_login", "slug", name="uq_harpo_secrets_login_slug"),
)
```

- [ ] **Étape 2 : Créer `backend/alembic/versions/014_harpo_secrets.py`**

```python
"""Tour 12 : table harpo_secrets.

Revision ID: 014
Revises: 013
Create Date: 2026-06-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "harpo_secrets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("secret_type", sa.Text(), nullable=False),
        sa.Column("secret_value_local", sa.LargeBinary(), nullable=True),
        sa.Column("secret_value_vault_ref", sa.Text(), nullable=True),
        sa.Column("storage_type", sa.Text(), nullable=False),
        sa.Column("vault_identifier", sa.Text(), nullable=True),
        sa.Column(
            "owner_login",
            sa.Text(),
            sa.ForeignKey("users.login", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("owner_login", "slug", name="uq_harpo_secrets_login_slug"),
    )
    op.create_index("idx_harpo_secrets_type", "harpo_secrets", ["secret_type"])
    op.create_index("idx_harpo_secrets_public", "harpo_secrets", ["is_public"])


def downgrade() -> None:
    op.drop_index("idx_harpo_secrets_public", table_name="harpo_secrets")
    op.drop_index("idx_harpo_secrets_type", table_name="harpo_secrets")
    op.drop_table("harpo_secrets")
```

- [ ] **Étape 3 : Vérifier la migration**

```bash
cd backend && uv run alembic upgrade head
```

Résultat attendu : `Running upgrade 013 -> 014`

- [ ] **Étape 4 : Lint + mypy**

```bash
cd backend && uv run ruff check src/portal/db/tables.py && uv run mypy src/portal/db/tables.py
```

- [ ] **Étape 5 : Commit**

```bash
git add backend/src/portal/db/tables.py backend/alembic/versions/014_harpo_secrets.py
git commit -m "feat(secrets): table harpo_secrets + migration 014"
```

---

## Tâche 2 — CRUD DB harpo_secrets

**Fichiers :**
- Créer : `backend/src/portal/db/secrets.py`
- Créer : `backend/tests/db/test_secrets.py`

**Interfaces produites :**
- `create_secret(owner_login, slug, label, description, secret_type, *, secret_value_local, secret_value_vault_ref, storage_type, vault_identifier, conn) -> None`
- `list_secrets(login, conn) -> list[dict]` — propres + publics, SANS `secret_value_local`
- `list_secrets_by_type(login, secret_type, conn) -> list[dict]` — filtre par type
- `get_secret(login, slug, conn) -> dict | None`
- `get_secret_value_local(login, slug, conn) -> bytes | None` — propriétaire uniquement
- `update_secret(login, slug, *, label, description, secret_value_local, secret_value_vault_ref, conn) -> bool`
- `delete_secret(login, slug, conn) -> dict | None`
- `set_secret_public(owner_login, slug, is_public, conn) -> bool`

- [ ] **Étape 1 : Écrire les tests**

Créer `backend/tests/db/test_secrets.py` :

```python
from __future__ import annotations

import uuid
import pytest
from sqlalchemy import insert
from portal.db.tables import users
from portal.db.secrets import (
    create_secret,
    delete_secret,
    get_secret,
    get_secret_value_local,
    list_secrets,
    list_secrets_by_type,
    set_secret_public,
    update_secret,
)

pytestmark = pytest.mark.asyncio

_VAL = b"\xAB" * 32


async def _user(conn, login: str = "alice") -> None:
    await conn.execute(insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4())))


async def test_create_and_list(db_conn):
    await _user(db_conn)
    await create_secret(
        "alice", "gh-pat", "GitHub PAT", "", "PAT_GITHUB",
        secret_value_local=_VAL, secret_value_vault_ref=None,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    rows = await list_secrets("alice", db_conn)
    assert len(rows) == 1
    assert rows[0]["slug"] == "gh-pat"
    assert "secret_value_local" not in rows[0]


async def test_list_by_type(db_conn):
    await _user(db_conn)
    await create_secret(
        "alice", "gh-pat", "GitHub PAT", "", "PAT_GITHUB",
        secret_value_local=_VAL, secret_value_vault_ref=None,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    await create_secret(
        "alice", "gh-api", "GitHub API", "", "API_KEY",
        secret_value_local=_VAL, secret_value_vault_ref=None,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    rows = await list_secrets_by_type("alice", "PAT_GITHUB", db_conn)
    assert len(rows) == 1
    assert rows[0]["slug"] == "gh-pat"


async def test_list_includes_public(db_conn):
    await _user(db_conn, "alice")
    await _user(db_conn, "bob")
    await create_secret(
        "bob", "shared", "Shared", "", "PAT_GITHUB",
        secret_value_local=_VAL, secret_value_vault_ref=None,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    await set_secret_public("bob", "shared", True, db_conn)
    rows = await list_secrets("alice", db_conn)
    assert any(r["slug"] == "shared" for r in rows)


async def test_get_secret_value_local_owner_only(db_conn):
    await _user(db_conn, "alice")
    await _user(db_conn, "bob")
    await create_secret(
        "alice", "s1", "S1", "", "PAT_GITHUB",
        secret_value_local=_VAL, secret_value_vault_ref=None,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    await set_secret_public("alice", "s1", True, db_conn)
    assert await get_secret_value_local("alice", "s1", db_conn) == _VAL
    assert await get_secret_value_local("bob", "s1", db_conn) is None


async def test_update_secret(db_conn):
    await _user(db_conn)
    await create_secret(
        "alice", "s1", "Old", "", "PAT_GITHUB",
        secret_value_local=_VAL, secret_value_vault_ref=None,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    new_val = b"\xFF" * 32
    ok = await update_secret("alice", "s1", label="New", description="desc",
                              secret_value_local=new_val, secret_value_vault_ref=None, conn=db_conn)
    assert ok
    blob = await get_secret_value_local("alice", "s1", db_conn)
    assert blob == new_val
    row = await get_secret("alice", "s1", db_conn)
    assert row is not None and row["label"] == "New"


async def test_delete_returns_row(db_conn):
    await _user(db_conn)
    await create_secret(
        "alice", "s1", "S1", "", "PAT_GITHUB",
        secret_value_local=_VAL, secret_value_vault_ref=None,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    row = await delete_secret("alice", "s1", db_conn)
    assert row is not None and row["slug"] == "s1"
    assert await list_secrets("alice", db_conn) == []
```

- [ ] **Étape 2 : Lancer les tests (vérifier échec)**

```bash
cd backend && uv run pytest tests/db/test_secrets.py -v
```

Résultat attendu : `ImportError: cannot import name 'create_secret'`

- [ ] **Étape 3 : Implémenter `backend/src/portal/db/secrets.py`**

```python
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import harpo_secrets

_PUBLIC_COLS = [
    harpo_secrets.c.slug,
    harpo_secrets.c.label,
    harpo_secrets.c.description,
    harpo_secrets.c.secret_type,
    harpo_secrets.c.secret_value_vault_ref,
    harpo_secrets.c.storage_type,
    harpo_secrets.c.vault_identifier,
    harpo_secrets.c.owner_login,
    harpo_secrets.c.is_public,
    harpo_secrets.c.created_at,
]


async def create_secret(
    owner_login: str,
    slug: str,
    label: str,
    description: str,
    secret_type: str,
    *,
    secret_value_local: bytes | None,
    secret_value_vault_ref: str | None,
    storage_type: str,
    vault_identifier: str | None,
    conn: AsyncConnection,
) -> None:
    await conn.execute(
        insert(harpo_secrets).values(
            owner_login=owner_login,
            slug=slug,
            label=label,
            description=description,
            secret_type=secret_type,
            secret_value_local=secret_value_local,
            secret_value_vault_ref=secret_value_vault_ref,
            storage_type=storage_type,
            vault_identifier=vault_identifier,
        )
    )


def _with_is_own(rows: list[Any], login: str) -> list[dict[str, Any]]:
    return [{**dict(r), "is_own": r["owner_login"] == login} for r in rows]


async def list_secrets(login: str, conn: AsyncConnection) -> list[dict[str, Any]]:
    q = (
        select(*_PUBLIC_COLS)
        .where(
            or_(
                harpo_secrets.c.owner_login == login,
                harpo_secrets.c.is_public.is_(True),
            )
        )
        .order_by(harpo_secrets.c.created_at)
    )
    rows = (await conn.execute(q)).mappings().all()
    return _with_is_own(list(rows), login)


async def list_secrets_by_type(
    login: str, secret_type: str, conn: AsyncConnection
) -> list[dict[str, Any]]:
    q = (
        select(*_PUBLIC_COLS)
        .where(
            harpo_secrets.c.secret_type == secret_type,
            or_(
                harpo_secrets.c.owner_login == login,
                harpo_secrets.c.is_public.is_(True),
            ),
        )
        .order_by(harpo_secrets.c.created_at)
    )
    rows = (await conn.execute(q)).mappings().all()
    return _with_is_own(list(rows), login)


async def get_secret(login: str, slug: str, conn: AsyncConnection) -> dict[str, Any] | None:
    q = select(*_PUBLIC_COLS).where(
        harpo_secrets.c.slug == slug,
        or_(
            harpo_secrets.c.owner_login == login,
            harpo_secrets.c.is_public.is_(True),
        ),
    )
    row = (await conn.execute(q)).mappings().first()
    if row is None:
        return None
    return {**dict(row), "is_own": row["owner_login"] == login}


async def get_secret_value_local(login: str, slug: str, conn: AsyncConnection) -> bytes | None:
    """Retourne secret_value_local uniquement si login est propriétaire."""
    q = select(harpo_secrets.c.secret_value_local).where(
        harpo_secrets.c.slug == slug,
        harpo_secrets.c.owner_login == login,
    )
    row = (await conn.execute(q)).first()
    return row[0] if row else None


async def update_secret(
    login: str,
    slug: str,
    *,
    label: str,
    description: str,
    secret_value_local: bytes | None,
    secret_value_vault_ref: str | None,
    conn: AsyncConnection,
) -> bool:
    values: dict[str, Any] = {"label": label, "description": description}
    if secret_value_local is not None:
        values["secret_value_local"] = secret_value_local
        values["secret_value_vault_ref"] = None
    elif secret_value_vault_ref is not None:
        values["secret_value_vault_ref"] = secret_value_vault_ref
        values["secret_value_local"] = None
    q = (
        update(harpo_secrets)
        .where(
            harpo_secrets.c.owner_login == login,
            harpo_secrets.c.slug == slug,
        )
        .values(**values)
        .returning(harpo_secrets.c.slug)
    )
    row = (await conn.execute(q)).first()
    return row is not None


async def delete_secret(login: str, slug: str, conn: AsyncConnection) -> dict[str, Any] | None:
    q = (
        delete(harpo_secrets)
        .where(
            harpo_secrets.c.owner_login == login,
            harpo_secrets.c.slug == slug,
        )
        .returning(*_PUBLIC_COLS, harpo_secrets.c.secret_value_vault_ref)
    )
    row = (await conn.execute(q)).mappings().first()
    return dict(row) if row else None


async def set_secret_public(
    owner_login: str, slug: str, is_public: bool, conn: AsyncConnection
) -> bool:
    q = (
        update(harpo_secrets)
        .where(
            harpo_secrets.c.owner_login == owner_login,
            harpo_secrets.c.slug == slug,
        )
        .values(is_public=is_public)
        .returning(harpo_secrets.c.slug)
    )
    row = (await conn.execute(q)).first()
    return row is not None
```

- [ ] **Étape 4 : Lancer les tests**

```bash
cd backend && uv run pytest tests/db/test_secrets.py -v
```

Résultat attendu : 7 tests PASSED (ou skipped si Docker absent)

- [ ] **Étape 5 : Lint + mypy**

```bash
cd backend && uv run ruff check src/portal/db/secrets.py tests/db/test_secrets.py
cd backend && uv run mypy src/portal/db/secrets.py
```

- [ ] **Étape 6 : Commit**

```bash
git add backend/src/portal/db/secrets.py backend/tests/db/test_secrets.py
git commit -m "feat(secrets): CRUD DB harpo_secrets"
```

---

## Tâche 3 — Service métier harpo_secrets

**Fichiers :**
- Créer : `backend/src/portal/secrets/__init__.py`
- Créer : `backend/src/portal/secrets/service.py`
- Créer : `backend/tests/secrets/__init__.py`
- Créer : `backend/tests/secrets/test_service.py`

**Interfaces consommées :**
- `create_secret, list_secrets, list_secrets_by_type, get_secret, get_secret_value_local, update_secret, delete_secret` (Tâche 2)
- `encrypt_token, decrypt_token` depuis `portal.vault.crypto`
- `get_master_key`, `vault_session` depuis `portal.vault.session`
- `get_vault_client` depuis `portal.vault.keys`

**Interfaces produites :**
- `class VaultLocked(Exception)`
- `class SecretAlreadyExists(Exception)`
- `class SecretNotFound(Exception)`
- `register_secret(login, session_id, slug, label, description, secret_type, secret_value, *, storage_type, vault_identifier, conn) -> None`
- `list_user_secrets(login, conn) -> list[dict]`
- `list_user_secrets_by_type(login, secret_type, conn) -> list[dict]`
- `reveal_secret(login, session_id, slug, conn) -> str`
- `edit_secret(login, session_id, slug, label, description, new_value, conn) -> None`
- `remove_secret(login, session_id, slug, conn) -> None`

- [ ] **Étape 1 : Écrire les tests**

Créer `backend/tests/secrets/test_service.py` :

```python
from __future__ import annotations

import uuid
import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection
from portal.db.tables import users
from portal.secrets.service import (
    SecretAlreadyExists,
    SecretNotFound,
    VaultLocked,
    edit_secret,
    list_user_secrets,
    list_user_secrets_by_type,
    register_secret,
    remove_secret,
    reveal_secret,
)
from portal.vault import session as vault_session

pytestmark = pytest.mark.asyncio

_SID = "test-session-xyz"
_MASTER = b"\x02" * 32
_VAL = "ghp_test_token_12345"


async def _user(conn: AsyncConnection, login: str = "alice") -> None:
    await conn.execute(insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4())))


async def test_register_and_list(db_conn: AsyncConnection):
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)
    await register_secret(
        "alice", _SID, "gh-pat", "GitHub PAT", "", "PAT_GITHUB", _VAL,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    rows = await list_user_secrets("alice", db_conn)
    assert len(rows) == 1
    assert rows[0]["slug"] == "gh-pat"
    assert "secret_value_local" not in rows[0]


async def test_register_duplicate_raises(db_conn: AsyncConnection):
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)
    await register_secret(
        "alice", _SID, "gh-pat", "GitHub PAT", "", "PAT_GITHUB", _VAL,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    with pytest.raises(SecretAlreadyExists):
        await register_secret(
            "alice", _SID, "gh-pat", "GitHub PAT 2", "", "PAT_GITHUB", _VAL,
            storage_type="local", vault_identifier=None, conn=db_conn,
        )


async def test_vault_locked_raises(db_conn: AsyncConnection):
    await _user(db_conn)
    with pytest.raises(VaultLocked):
        await register_secret(
            "alice", "no-session", "gh-pat", "X", "", "PAT_GITHUB", _VAL,
            storage_type="local", vault_identifier=None, conn=db_conn,
        )


async def test_reveal_secret(db_conn: AsyncConnection):
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)
    await register_secret(
        "alice", _SID, "gh-pat", "GitHub PAT", "", "PAT_GITHUB", _VAL,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    plain = await reveal_secret("alice", _SID, "gh-pat", db_conn)
    assert plain == _VAL


async def test_edit_secret(db_conn: AsyncConnection):
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)
    await register_secret(
        "alice", _SID, "gh-pat", "GitHub PAT", "", "PAT_GITHUB", _VAL,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    new_val = "ghp_updated_token_99999"
    await edit_secret("alice", _SID, "gh-pat", "GitHub PAT v2", "desc", new_val, db_conn)
    plain = await reveal_secret("alice", _SID, "gh-pat", db_conn)
    assert plain == new_val
    rows = await list_user_secrets("alice", db_conn)
    assert rows[0]["label"] == "GitHub PAT v2"


async def test_remove_secret(db_conn: AsyncConnection):
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)
    await register_secret(
        "alice", _SID, "gh-pat", "GitHub PAT", "", "PAT_GITHUB", _VAL,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    await remove_secret("alice", _SID, "gh-pat", db_conn)
    assert await list_user_secrets("alice", db_conn) == []


async def test_remove_nonexistent_raises(db_conn: AsyncConnection):
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)
    with pytest.raises(SecretNotFound):
        await remove_secret("alice", _SID, "ghost", db_conn)


async def test_list_by_type(db_conn: AsyncConnection):
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)
    await register_secret("alice", _SID, "gh-pat", "GH", "", "PAT_GITHUB", _VAL,
                           storage_type="local", vault_identifier=None, conn=db_conn)
    await register_secret("alice", _SID, "api-key", "API", "", "API_KEY", _VAL,
                           storage_type="local", vault_identifier=None, conn=db_conn)
    rows = await list_user_secrets_by_type("alice", "PAT_GITHUB", db_conn)
    assert len(rows) == 1 and rows[0]["slug"] == "gh-pat"
```

- [ ] **Étape 2 : Lancer les tests (vérifier échec)**

```bash
cd backend && uv run pytest tests/secrets/test_service.py -v
```

Résultat attendu : `ImportError`

- [ ] **Étape 3 : Implémenter `backend/src/portal/secrets/service.py`**

```python
from __future__ import annotations

from collections.abc import Callable

import anyio
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db.secrets import (
    create_secret,
    delete_secret,
    get_secret,
    get_secret_value_local,
    list_secrets,
    list_secrets_by_type,
    update_secret,
)
from ..vault import session as vault_session
from ..vault.crypto import decrypt_token, encrypt_token
from ..vault.keys import get_vault_client

_log = structlog.get_logger(__name__)

_VAULT_PATH = "secrets/{slug}/value"


class VaultLocked(Exception):
    pass


class SecretAlreadyExists(Exception):
    pass


class SecretNotFound(Exception):
    pass


def _require_master_key(session_id: str) -> bytes:
    mk = vault_session.get_master_key(session_id)
    if mk is None:
        raise VaultLocked("Vault verrouillé — déverrouillez avec votre PIN")
    return mk


def _make_harpo_write(client: object, slug: str, value: str) -> Callable[[], None]:
    def _write() -> None:
        client.secrets.create(_VAULT_PATH.format(slug=slug), value)  # type: ignore[attr-defined]
    return _write


def _make_harpo_update(client: object, slug: str, value: str) -> Callable[[], None]:
    def _update() -> None:
        client.secrets.put(_VAULT_PATH.format(slug=slug), value)  # type: ignore[attr-defined]
    return _update


def _make_harpo_delete(client: object, slug: str) -> Callable[[], None]:
    def _delete() -> None:
        client.secrets.delete(_VAULT_PATH.format(slug=slug))  # type: ignore[attr-defined]
    return _delete


async def register_secret(
    login: str,
    session_id: str,
    slug: str,
    label: str,
    description: str,
    secret_type: str,
    secret_value: str,
    *,
    storage_type: str,
    vault_identifier: str | None,
    conn: AsyncConnection,
) -> None:
    master_key = _require_master_key(session_id)

    if storage_type == "local":
        encrypted = encrypt_token(secret_value, master_key)
        vault_ref = None
        harpo_write = None
    else:
        encrypted = None
        vault_ref = f"${{vault://{vault_identifier}:secrets/{slug}/value}}"
        client = await get_vault_client(login, session_id, vault_identifier, conn)
        harpo_write = _make_harpo_write(client, slug, secret_value)

    try:
        await create_secret(
            login, slug, label, description, secret_type,
            secret_value_local=encrypted,
            secret_value_vault_ref=vault_ref,
            storage_type=storage_type,
            vault_identifier=vault_identifier,
            conn=conn,
        )
    except IntegrityError as exc:
        raise SecretAlreadyExists(f"Un secret '{slug}' existe déjà") from exc

    if harpo_write is not None:
        await anyio.to_thread.run_sync(harpo_write)
    _log.info("secret_registered", login=login, slug=slug, storage_type=storage_type)


async def list_user_secrets(login: str, conn: AsyncConnection) -> list[dict]:
    return await list_secrets(login, conn)


async def list_user_secrets_by_type(
    login: str, secret_type: str, conn: AsyncConnection
) -> list[dict]:
    return await list_secrets_by_type(login, secret_type, conn)


async def reveal_secret(
    login: str, session_id: str, slug: str, conn: AsyncConnection
) -> str:
    master_key = _require_master_key(session_id)
    blob = await get_secret_value_local(login, slug, conn)
    if blob is not None:
        return decrypt_token(blob, master_key)
    row = await get_secret(login, slug, conn)
    if row is None:
        raise SecretNotFound(f"Secret '{slug}' introuvable")
    if row["storage_type"] != "harpocrate" or row["owner_login"] != login:
        raise SecretNotFound("Valeur inaccessible")
    client = await get_vault_client(login, session_id, row["vault_identifier"], conn)
    return await anyio.to_thread.run_sync(
        lambda: client.secrets.get(_VAULT_PATH.format(slug=slug))
    )


async def edit_secret(
    login: str,
    session_id: str,
    slug: str,
    label: str,
    description: str,
    new_value: str | None,
    conn: AsyncConnection,
) -> None:
    master_key = _require_master_key(session_id)
    row = await get_secret(login, slug, conn)
    if row is None or row["owner_login"] != login:
        raise SecretNotFound(f"Secret '{slug}' introuvable ou non autorisé")

    new_local: bytes | None = None
    new_vault_ref: str | None = None

    if new_value is not None:
        if row["storage_type"] == "local":
            new_local = encrypt_token(new_value, master_key)
        else:
            client = await get_vault_client(login, session_id, row["vault_identifier"], conn)
            await anyio.to_thread.run_sync(_make_harpo_update(client, slug, new_value))
            new_vault_ref = row["secret_value_vault_ref"]

    ok = await update_secret(
        login, slug,
        label=label,
        description=description,
        secret_value_local=new_local,
        secret_value_vault_ref=new_vault_ref,
        conn=conn,
    )
    if not ok:
        raise SecretNotFound(f"Secret '{slug}' introuvable")
    _log.info("secret_edited", login=login, slug=slug)


async def remove_secret(
    login: str, session_id: str, slug: str, conn: AsyncConnection
) -> None:
    _require_master_key(session_id)
    row = await delete_secret(login, slug, conn)
    if row is None:
        raise SecretNotFound(f"Secret '{slug}' introuvable ou non autorisé")
    if row["storage_type"] == "harpocrate" and row.get("vault_identifier"):
        client = await get_vault_client(login, session_id, row["vault_identifier"], conn)
        try:
            await anyio.to_thread.run_sync(_make_harpo_delete(client, slug))
        except Exception:
            _log.warning("secret_vault_delete_failed", slug=slug)
    _log.info("secret_removed", login=login, slug=slug)
```

- [ ] **Étape 4 : Lancer les tests**

```bash
cd backend && uv run pytest tests/secrets/test_service.py -v
```

Résultat attendu : 8 tests PASSED (ou skipped si Docker absent)

- [ ] **Étape 5 : Lint + mypy**

```bash
cd backend && uv run ruff check src/portal/secrets/service.py && uv run mypy src/portal/secrets/service.py
```

- [ ] **Étape 6 : Commit**

```bash
git add backend/src/portal/secrets/ backend/tests/secrets/
git commit -m "feat(secrets): service métier harpo_secrets (register, reveal, edit, remove)"
```

---

## Tâche 4 — Routes FastAPI secrets + enregistrement

**Fichiers :**
- Créer : `backend/src/portal/routes/secrets.py`
- Modifier : `backend/src/portal/app.py`

**Endpoints :**
- `GET /me/secrets` → `list[dict]`
- `GET /me/secrets?type=PAT_GITHUB` → filtre par type
- `POST /me/secrets` → enregistrer un secret
- `PATCH /me/secrets/{slug}` → éditer label/description/valeur
- `GET /me/secrets/{slug}/value` → révéler la valeur (audit log)
- `DELETE /me/secrets/{slug}` → 204
- `PATCH /admin/secrets/{owner_login}/{slug}/visibility` → toggle is_public

**Validation slug :** `^[a-z0-9][a-z0-9_-]{0,62}$`

**Gestion erreurs (codes opaques) :**
- `VaultLocked` → 403 `"vault_locked"`
- `SecretAlreadyExists` → 409 `"secret_already_exists"`
- `SecretNotFound` → 404 `"secret_not_found"`

- [ ] **Étape 1 : Créer `backend/src/portal/routes/secrets.py`**

```python
from __future__ import annotations

import re
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin, require_user
from ..db.secrets import set_secret_public
from ..db.engine import get_conn
from ..secrets.service import (
    SecretAlreadyExists,
    SecretNotFound,
    VaultLocked,
    edit_secret,
    list_user_secrets,
    list_user_secrets_by_type,
    register_secret,
    remove_secret,
    reveal_secret,
)

_log = structlog.get_logger(__name__)
router_me = APIRouter(tags=["secrets"])
router_admin = APIRouter(tags=["admin-secrets"])

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")

SECRET_TYPES = Literal["PAT_GITHUB", "PAT_GITLAB", "PAT_AZURE", "API_KEY"]


def _sid(request: Request) -> str:
    return str(request.session.get("session_id", ""))


def _handle_common(exc: Exception) -> None:
    if isinstance(exc, VaultLocked):
        raise HTTPException(status_code=403, detail="vault_locked") from exc
    if isinstance(exc, SecretAlreadyExists):
        raise HTTPException(status_code=409, detail="secret_already_exists") from exc
    if isinstance(exc, SecretNotFound):
        raise HTTPException(status_code=404, detail="secret_not_found") from exc


class RegisterBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    label: str
    description: str = ""
    secret_type: str
    secret_value: str
    storage_type: Literal["local", "harpocrate"] = "local"
    vault_identifier: str | None = None

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not _SLUG_RE.fullmatch(v):
            raise ValueError("slug: alphanum minuscules + tirets/underscores")
        return v


class EditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    description: str = ""
    new_value: str | None = None


class VisibilityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_public: bool


@router_me.get("/secrets")
async def list_my_secrets(
    request: Request,
    secret_type: str | None = Query(default=None),
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    if secret_type:
        return await list_user_secrets_by_type(user.login, secret_type, conn)
    return await list_user_secrets(user.login, conn)


@router_me.post("/secrets", status_code=201)
async def register_my_secret(
    body: RegisterBody,
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        await register_secret(
            user.login, _sid(request), body.slug, body.label, body.description,
            body.secret_type, body.secret_value,
            storage_type=body.storage_type,
            vault_identifier=body.vault_identifier,
            conn=conn,
        )
    except Exception as exc:
        _handle_common(exc)
        raise
    return {"slug": body.slug}


@router_me.patch("/secrets/{slug}")
async def edit_my_secret(
    body: EditBody,
    request: Request,
    slug: str = Path(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$"),
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        await edit_secret(
            user.login, _sid(request), slug,
            body.label, body.description, body.new_value, conn,
        )
    except Exception as exc:
        _handle_common(exc)
        raise
    return {"slug": slug}


@router_me.get("/secrets/{slug}/value")
async def get_secret_value(
    request: Request,
    slug: str = Path(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$"),
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        value = await reveal_secret(user.login, _sid(request), slug, conn)
    except Exception as exc:
        _handle_common(exc)
        raise
    _log.info("secret_value_accessed", login=user.login, slug=slug)
    return {"secret_value": value}


@router_me.delete("/secrets/{slug}", status_code=204)
async def delete_my_secret(
    request: Request,
    slug: str = Path(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$"),
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    try:
        await remove_secret(user.login, _sid(request), slug, conn)
    except Exception as exc:
        _handle_common(exc)
        raise


@router_admin.patch("/secrets/{owner_login}/{slug}/visibility")
async def set_visibility(
    body: VisibilityBody,
    owner_login: str = Path(..., min_length=1, max_length=128),
    slug: str = Path(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$"),
    _user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    ok = await set_secret_public(owner_login, slug, body.is_public, conn)
    if not ok:
        raise HTTPException(status_code=404, detail="secret_not_found")
    return {"owner_login": owner_login, "slug": slug, "is_public": body.is_public}
```

- [ ] **Étape 2 : Enregistrer dans `app.py`**

Dans `backend/src/portal/app.py`, après les imports des routers certificates :

```python
from .routes.secrets import router_admin as secrets_admin_router
from .routes.secrets import router_me as secrets_me_router
```

Et dans `create_app()` après les routers certificates :

```python
app.include_router(secrets_me_router, prefix="/me")
app.include_router(secrets_admin_router, prefix="/admin")
```

- [ ] **Étape 3 : Vérifier le démarrage**

```bash
cd backend && uv run python -c "from portal.app import app; routes = [r.path for r in app.routes if 'secret' in getattr(r,'path','')]; print(routes)"
```

Résultat attendu : liste contenant `/me/secrets`, `/me/secrets/{slug}`, `/me/secrets/{slug}/value`, `/admin/secrets/{owner_login}/{slug}/visibility`

- [ ] **Étape 4 : Lint + mypy**

```bash
cd backend && uv run ruff check src/portal/routes/secrets.py && uv run mypy src/portal/routes/secrets.py
```

- [ ] **Étape 5 : Commit**

```bash
git add backend/src/portal/routes/secrets.py backend/src/portal/app.py
git commit -m "feat(secrets): routes FastAPI /me/secrets + /admin/secrets"
```

---

## Tâche 5 — Frontend hooks + SecretsTab + CredentialsPage

**Fichiers :**
- Créer : `frontend/src/features/secrets/api.ts`
- Créer : `frontend/src/features/secrets/SecretsTab.tsx`
- Modifier : `frontend/src/features/git-credentials/CredentialsPage.tsx`
- Modifier : `frontend/src/i18n/fr.json`
- Modifier : `frontend/src/i18n/en.json`

**Hooks à exporter depuis `api.ts` :**
- `SecretType` : `'PAT_GITHUB' | 'PAT_GITLAB' | 'PAT_AZURE' | 'API_KEY'`
- `Secret` interface (tous les champs backend + `is_own: boolean`)
- `useSecrets(secretType?: string)` → query `['secrets']` (ou `['secrets', type]`)
- `useRegisterSecret()` → mutation POST /me/secrets
- `useEditSecret()` → mutation PATCH /me/secrets/{slug}
- `useRevealSecret()` → mutation (pas query) GET /me/secrets/{slug}/value
- `useDeleteSecret()` → mutation DELETE /me/secrets/{slug}
- `useSetSecretVisibility()` → mutation PATCH /admin/secrets/{owner_login}/{slug}/visibility

**SecretsTab :**
- Structure identique à `CertificatesTab` (liste + dialog Ajouter + dialog Éditer)
- Dialog Ajouter : label → slug auto, type dropdown (`SECRET_TYPES`), valeur (input password), stockage local/harpocrate + wallet selector
- Dialog Éditer : pré-remplir label/description, champ optionnel "Nouvelle valeur" (laisser vide = ne pas changer)
- Bouton "Révéler" : uniquement si `is_own === true`
- Bouton "Modifier" : uniquement si `is_own === true`
- Badge "Public" si `is_public === true`
- Suppression avec confirmation

**CredentialsPage :**
- Ajouter onglet `secrets` entre `certificates` et `git` :

```tsx
import SecretsTab from '@/features/secrets/SecretsTab'
// Dans TabsList :
<TabsTrigger value="secrets">{t('secrets.tabLabel')}</TabsTrigger>
// Dans TabsContent :
<TabsContent value="secrets" className="mt-0"><SecretsTab /></TabsContent>
```

**Clés i18n à ajouter dans `fr.json` et `en.json` :**

```json
"secrets": {
  "tabLabel": "Secrets",
  "title": "Secrets & Tokens",
  "info": "Gérez vos tokens d'API et PAT. Les valeurs sont chiffrées avec votre PIN vault.",
  "addSecret": "Ajouter",
  "noSecrets": "Aucun secret enregistré.",
  "publicBadge": "Public",
  "revealValue": "Révéler la valeur",
  "hideValue": "Masquer la valeur",
  "valueLabel": "Valeur",
  "copied": "Copié !",
  "copy": "Copier",
  "confirmDelete": "Confirmer la suppression",
  "dialogAddTitle": "Enregistrer un secret",
  "dialogEditTitle": "Modifier le secret",
  "form": {
    "label": "Nom",
    "labelPlaceholder": "ex : GitHub Personal Token",
    "slug": "Identifiant (slug)",
    "slugEmpty": "auto",
    "description": "Description",
    "descriptionPlaceholder": "À quoi sert ce token ?",
    "secretType": "Type",
    "secretValue": "Valeur du secret",
    "secretValuePlaceholder": "ghp_…",
    "newValue": "Nouvelle valeur (laisser vide pour conserver l'actuelle)",
    "storageType": "Stockage",
    "storageLocal": "Local (chiffré en base)",
    "storageHarpocrate": "Wallet Harpocrate",
    "vaultWallet": "Wallet",
    "saving": "Enregistrement…",
    "save": "Enregistrer"
  },
  "types": {
    "PAT_GITHUB": "Personal Access Token — GitHub",
    "PAT_GITLAB": "Personal Access Token — GitLab",
    "PAT_AZURE": "Personal Access Token — Azure DevOps",
    "API_KEY": "Clé API générique"
  }
}
```

- [ ] **Étape 1 : Créer `frontend/src/features/secrets/api.ts`** (suivre exactement le pattern de `certificates/api.ts`)

- [ ] **Étape 2 : Créer `frontend/src/features/secrets/SecretsTab.tsx`** (suivre exactement le pattern de `CertificatesTab.tsx`, sans la partie génération server-side)

- [ ] **Étape 3 : Ajouter les clés i18n dans `fr.json` et `en.json`**

- [ ] **Étape 4 : Modifier `CredentialsPage.tsx`** — ajouter onglet secrets entre certificates et git

- [ ] **Étape 5 : Vérifier TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

Résultat attendu : 0 erreur

- [ ] **Étape 6 : Commit**

```bash
git add frontend/src/features/secrets/ frontend/src/features/git-credentials/CredentialsPage.tsx frontend/src/i18n/
git commit -m "feat(secrets): onglet Secrets UI + i18n + intégration CredentialsPage"
```

---

## Tâche 6 — Édition certificats (backend + frontend)

**Fichiers :**
- Modifier : `backend/src/portal/db/certificates.py`
- Modifier : `backend/src/portal/certificates/service.py`
- Modifier : `backend/src/portal/routes/certificates.py`
- Modifier : `frontend/src/features/certificates/api.ts`
- Modifier : `frontend/src/features/certificates/CertificatesTab.tsx`

**Backend — `update_certificate` dans `db/certificates.py` :**

```python
async def update_certificate(
    login: str,
    slug: str,
    *,
    label: str,
    description: str,
    public_key: str | None,
    private_key_local: bytes | None,
    private_key_vault_ref: str | None,
    conn: AsyncConnection,
) -> bool:
    values: dict[str, Any] = {"label": label, "description": description}
    if public_key is not None:
        values["public_key"] = public_key
    if private_key_local is not None:
        values["private_key_local"] = private_key_local
        values["private_key_vault_ref"] = None
    elif private_key_vault_ref is not None:
        values["private_key_vault_ref"] = private_key_vault_ref
        values["private_key_local"] = None
    q = (
        update(harpo_certificates)
        .where(
            harpo_certificates.c.owner_login == login,
            harpo_certificates.c.slug == slug,
        )
        .values(**values)
        .returning(harpo_certificates.c.slug)
    )
    row = (await conn.execute(q)).first()
    return row is not None
```

**Backend — `edit_certificate` dans `certificates/service.py` :**

```python
async def edit_certificate(
    login: str,
    session_id: str,
    slug: str,
    label: str,
    description: str,
    new_public_key: str | None,
    new_private_key_pem: str | None,
    conn: AsyncConnection,
) -> None:
    master_key = _require_master_key(session_id)
    row = await get_certificate(login, slug, conn)
    if row is None or row["owner_login"] != login:
        raise CertNotFound(f"Certificat '{slug}' introuvable ou non autorisé")

    new_local: bytes | None = None
    new_vault_ref: str | None = None

    if new_private_key_pem is not None:
        if row["storage_type"] == "local":
            new_local = encrypt_token(new_private_key_pem, master_key)
        else:
            client = await get_vault_client(login, session_id, row["vault_identifier"], conn)
            await anyio.to_thread.run_sync(
                lambda: client.secrets.put(
                    f"certificats/{slug}/private", new_private_key_pem
                )
            )
            if new_public_key is not None:
                await anyio.to_thread.run_sync(
                    lambda: client.secrets.put(
                        f"certificats/{slug}/public", new_public_key
                    )
                )
            new_vault_ref = row["private_key_vault_ref"]

    ok = await update_certificate(
        login, slug,
        label=label,
        description=description,
        public_key=new_public_key,
        private_key_local=new_local,
        private_key_vault_ref=new_vault_ref,
        conn=conn,
    )
    if not ok:
        raise CertNotFound(f"Certificat '{slug}' introuvable")
    _log.info("certificate_edited", login=login, slug=slug)
```

**Route PATCH /me/certificates/{slug} :**

```python
class EditCertBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    description: str = ""
    new_public_key: str | None = None
    new_private_key_pem: str | None = None

@router_me.patch("/certificates/{slug}")
async def edit_cert(
    body: EditCertBody,
    request: Request,
    slug: str = Path(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$"),
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        await edit_certificate(
            user.login, _sid(request), slug,
            body.label, body.description,
            body.new_public_key, body.new_private_key_pem,
            conn,
        )
    except Exception as exc:
        _handle_common(exc)
        raise
    return {"slug": slug}
```

**Frontend — `useUpdateCertificate` dans `certificates/api.ts` :**

```typescript
export interface EditCertBody {
  label: string
  description?: string
  new_public_key?: string | null
  new_private_key_pem?: string | null
}

export function useUpdateCertificate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ slug, ...body }: EditCertBody & { slug: string }) =>
      apiFetchJson<{ slug: string }>(
        `/me/certificates/${encodeURIComponent(slug)}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.list() }),
  })
}
```

**Frontend — Dialog Edit dans `CertificatesTab.tsx` :**

Ajouter dans `CertRow` un bouton "Modifier" (icône `Pencil`) qui ouvre un `EditDialog` pré-rempli avec `cert.label`, `cert.description`, et deux champs optionnels "Nouvelle clé publique" / "Nouvelle clé privée (PEM)".

- [ ] **Étape 1 : Ajouter `update_certificate` dans `db/certificates.py`**
- [ ] **Étape 2 : Ajouter `edit_certificate` dans `certificates/service.py`** + import `update_certificate`
- [ ] **Étape 3 : Ajouter `EditCertBody` et route PATCH dans `routes/certificates.py`**
- [ ] **Étape 4 : Ajouter `useUpdateCertificate` dans `frontend/src/features/certificates/api.ts`**
- [ ] **Étape 5 : Ajouter dialog Edit dans `CertificatesTab.tsx`**
- [ ] **Étape 6 : Lint + mypy backend + tsc frontend**

```bash
cd backend && uv run ruff check src/portal/db/certificates.py src/portal/certificates/service.py src/portal/routes/certificates.py
cd backend && uv run mypy src/portal/db/certificates.py src/portal/certificates/service.py src/portal/routes/certificates.py
cd frontend && npx tsc --noEmit
```

- [ ] **Étape 7 : Commit**

```bash
git add backend/src/portal/db/certificates.py backend/src/portal/certificates/service.py backend/src/portal/routes/certificates.py frontend/src/features/certificates/
git commit -m "feat(certificates): édition label/description/clés (PATCH /me/certificates/{slug})"
```

---

## Tâche 7 — Alignement Git Credentials : sélecteur PAT depuis harpo_secrets

**Contexte :** Dans `GitCredentialManager.tsx`, quand `kind === 'token'`, ajouter un toggle "Choisir depuis mes secrets" qui affiche un dropdown des secrets `PAT_GITHUB` ou `PAT_GITLAB` enregistrés (selon le host sélectionné), et utilise leur valeur au moment de la soumission.

**Fichiers :**
- Modifier : `frontend/src/features/git-credentials/GitCredentialManager.tsx`
- Modifier : `frontend/src/i18n/fr.json` + `en.json`

**Logique :**
- Quand `kind === 'token'`, afficher un switch "Utiliser un secret enregistré"
- Si activé : remplacer le champ texte du token par un `<Select>` alimenté par `useSecrets('PAT_GITHUB')` (ou `PAT_GITLAB` selon le host)
- La valeur sélectionnée stocke le `slug` du secret
- Au submit, si mode "secret", appeler `GET /me/secrets/{slug}/value` pour récupérer la valeur déchiffrée, puis procéder comme d'habitude

**Note :** Le token envoyé au backend reste le même payload — on récupère d'abord la valeur en clair du secret (via `reveal_secret`/`useRevealSecret`) avant de soumettre le form. Ainsi l'API git credentials existante ne change pas.

**Mapping host → type de secret :**
```typescript
const HOST_TO_SECRET_TYPE: Record<string, string> = {
  'github.com': 'PAT_GITHUB',
  'gitlab.com': 'PAT_GITLAB',
  'bitbucket.org': 'API_KEY',
  'dev.azure.com': 'PAT_AZURE',
}
```

**Clés i18n à ajouter :**
```json
"gitCredentials": {
  "useRegisteredSecret": "Utiliser un secret enregistré",
  "selectSecret": "Choisir un secret…",
  "noSecretsForHost": "Aucun secret disponible pour cet hôte — enregistrez-en un dans l'onglet Secrets"
}
```

- [ ] **Étape 1 : Ajouter les clés i18n** dans `fr.json` et `en.json`
- [ ] **Étape 2 : Modifier `GitCredentialManager.tsx`**
  - Ajouter state `useRegisteredSecret: boolean` et `selectedSecretSlug: string`
  - Importer `useSecrets` depuis `@/features/secrets/api`
  - Importer `useRevealSecret` depuis `@/features/secrets/api`
  - Dans le bloc `kind === 'token'` du form Add : afficher un switch + Select conditionnel
  - Dans `handleAdd` : si `useRegisteredSecret`, appeler `reveal_secret(selectedSecretSlug)` et utiliser la valeur retournée comme `token`
  - Même chose dans le form Edit
- [ ] **Étape 3 : Vérifier TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

Résultat attendu : 0 erreur

- [ ] **Étape 4 : Commit**

```bash
git add frontend/src/features/git-credentials/GitCredentialManager.tsx frontend/src/i18n/
git commit -m "feat(git-credentials): sélecteur PAT depuis harpo_secrets (switch inline/secret)"
```

---

## Auto-vérification spec

| Exigence | Tâche |
|---|---|
| Table `harpo_secrets` avec slug, label, type, valeur chiffrée | T1 |
| Stockage local AES-GCM OU harpocrate | T3 |
| Valeur jamais en clair dans les logs | T3 |
| CRUD + filtre par type | T2, T4 |
| Édition label + description + valeur (re-chiffrement) | T3 (secrets), T6 (certs) |
| Harpocrate edit = `client.secrets.put()` | T3 |
| Onglet Secrets entre Certificats et Git | T5 |
| Git Credentials : sélecteur PAT depuis harpo_secrets | T7 |
| Codes erreur opaques (pas `str(exc)`) | T4 |
| Slug scopé à (owner_login, slug) dans set_secret_public | T2 |
| IDOR impossible (owner_login dans PATCH visibility) | T2, T4 |
