# Harpo Certificates — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centraliser la gestion des paires de clés (SSH et TLS) dans une table `harpo_certificates`, avec génération server-side, stockage local chiffré ou dans un wallet Harpocrate, et un onglet dédié dans l'UI.

**Architecture:** DB table par utilisateur (+ certs publics admin) ; clé privée chiffrée AES-GCM avec la master key vault (PIN requis) pour le stockage local, ou écrite dans le wallet Harpocrate et référencée dans la DB. Génération server-side via `cryptography`. Onglet "Certificats" entre Vault et Git Credentials.

**Tech Stack:** Python `cryptography`, FastAPI, SQLAlchemy Core async, pydantic v2, React 18 + TanStack Query + shadcn/ui + i18next.

## Global Constraints

- Python 3.12+, `from __future__ import annotations` en tête de chaque fichier Python
- Async/await partout — jamais `subprocess.run` ni I/O bloquant dans un handler
- pydantic v2, `extra="forbid"` sur tous les modèles
- `structlog.get_logger(__name__)` — jamais `print()`
- Clé privée : jamais en clair dans les logs ni dans les réponses de liste
- `safe_user_path` si chemin filesystem ; ici pas de filesystem → N/A
- `cryptography` est déjà dans `pyproject.toml`
- Branche `dev`, commits en français format conventionnel
- Tests : `pytest-asyncio`, fixture `db_conn` (testcontainers postgres)
- Fichiers max 300 lignes, méthodes 5-15 lignes

---

## Structure des fichiers

### Créés

| Fichier | Responsabilité |
|---|---|
| `backend/alembic/versions/011_harpo_certificates.py` | Migration SQL |
| `backend/src/portal/db/certificates.py` | CRUD bas niveau (insert/select/delete) |
| `backend/src/portal/certificates/__init__.py` | Package marker |
| `backend/src/portal/certificates/keygen.py` | Génération server-side (SSH + TLS) |
| `backend/src/portal/certificates/service.py` | Logique métier (create, list, get_private, delete + harpocrate) |
| `backend/src/portal/routes/certificates.py` | Endpoints FastAPI |
| `backend/tests/db/test_certificates.py` | Tests CRUD DB |
| `backend/tests/certificates/__init__.py` | Package marker |
| `backend/tests/certificates/test_keygen.py` | Tests génération clés |
| `backend/tests/certificates/test_service.py` | Tests service (stockage local) |
| `frontend/src/features/certificates/api.ts` | Hooks TanStack Query |
| `frontend/src/features/certificates/CertificatesTab.tsx` | Composant onglet |

### Modifiés

| Fichier | Changement |
|---|---|
| `backend/src/portal/db/tables.py` | Ajouter table `harpo_certificates` |
| `backend/src/portal/app.py` | Enregistrer `certificates_router` |
| `frontend/src/features/git-credentials/CredentialsPage.tsx` | Ajouter onglet Certificats |
| `frontend/src/i18n/fr.json` | Clés `certificates.*` |
| `frontend/src/i18n/en.json` | Clés `certificates.*` |

---

## Tâche 1 — Table DB + migration

**Fichiers :**
- Modifier : `backend/src/portal/db/tables.py`
- Créer : `backend/alembic/versions/011_harpo_certificates.py`

**Interfaces produites :**
- `harpo_certificates` : table SQLAlchemy avec colonnes `id, slug, label, description, cert_type, public_key, private_key_local, private_key_vault_ref, storage_type, vault_identifier, owner_login, is_public, created_at`

- [ ] **Étape 1 : Ajouter la table dans `tables.py`**

Ajouter à la fin de `backend/src/portal/db/tables.py` :

```python
# ─── Tour 11 : harpo_certificates ────────────────────────────────────────────

harpo_certificates = Table(
    "harpo_certificates",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("slug", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=""),
    # ssh-ed25519 | ssh-rsa-2048 | ssh-rsa-4096 | ssh-ecdsa-p256
    # tls-rsa-2048 | tls-rsa-4096 | tls-ec-p256 | tls-ec-p384
    Column("cert_type", Text, nullable=False),
    Column("public_key", Text, nullable=False),
    Column("private_key_local", LargeBinary, nullable=True),   # AES-GCM, master_key
    Column("private_key_vault_ref", Text, nullable=True),       # ${vault://id:certificats/slug/private}
    Column("storage_type", Text, nullable=False),               # local | harpocrate
    Column("vault_identifier", Text, nullable=True),
    Column("owner_login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("is_public", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("owner_login", "slug", name="uq_harpo_certs_login_slug"),
)
```

- [ ] **Étape 2 : Créer la migration**

Contenu de `backend/alembic/versions/011_harpo_certificates.py` :

```python
"""Tour 11 : table harpo_certificates.

Revision ID: 011
Revises: 010
Create Date: 2026-06-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "harpo_certificates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("cert_type", sa.Text(), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("private_key_local", sa.LargeBinary(), nullable=True),
        sa.Column("private_key_vault_ref", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("owner_login", "slug", name="uq_harpo_certs_login_slug"),
    )
    op.create_index("idx_harpo_certs_public", "harpo_certificates", ["is_public"])


def downgrade() -> None:
    op.drop_index("idx_harpo_certs_public", table_name="harpo_certificates")
    op.drop_table("harpo_certificates")
```

- [ ] **Étape 3 : Vérifier que la migration s'applique**

```bash
cd backend && uv run alembic upgrade head
```

Résultat attendu : `Running upgrade 010 -> 011`

- [ ] **Étape 4 : Commit**

```bash
git add backend/src/portal/db/tables.py backend/alembic/versions/011_harpo_certificates.py
git commit -m "feat(certificates): table harpo_certificates + migration 011"
```

---

## Tâche 2 — CRUD DB

**Fichiers :**
- Créer : `backend/src/portal/db/certificates.py`
- Créer : `backend/tests/db/test_certificates.py`

**Interfaces consommées :** `harpo_certificates` (Tâche 1)

**Interfaces produites :**
- `create_certificate(login, slug, label, description, cert_type, public_key, private_key_local, private_key_vault_ref, storage_type, vault_identifier, conn) -> None`
- `list_certificates(login, conn) -> list[dict]` — propres + publics, sans `private_key_local`
- `get_certificate(login, slug, conn) -> dict | None` — propre ou public
- `get_private_key_local(login, slug, conn) -> bytes | None`
- `delete_certificate(login, slug, conn) -> dict | None` — retourne la ligne pour cleanup harpocrate
- `set_public(slug, is_public, conn) -> bool` — admin uniquement

- [ ] **Étape 1 : Écrire les tests**

Créer `backend/tests/db/test_certificates.py` :

```python
from __future__ import annotations

import uuid
import pytest
from sqlalchemy import insert
from portal.db.tables import users
from portal.db.certificates import (
    create_certificate,
    delete_certificate,
    get_certificate,
    get_private_key_local,
    list_certificates,
    set_public,
)

pytestmark = pytest.mark.asyncio

_PUB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5 test"
_PRIV = b"\xAB" * 64


async def _user(conn, login: str = "alice") -> None:
    await conn.execute(insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4())))


async def test_create_and_list(db_conn):
    await _user(db_conn)
    await create_certificate(
        "alice", "gh-key", "GitHub", "", "ssh-ed25519", _PUB,
        private_key_local=_PRIV, private_key_vault_ref=None,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    rows = await list_certificates("alice", db_conn)
    assert len(rows) == 1
    assert rows[0]["slug"] == "gh-key"
    assert "private_key_local" not in rows[0]


async def test_list_includes_public_from_other_user(db_conn):
    await _user(db_conn, "alice")
    await _user(db_conn, "bob")
    await create_certificate(
        "bob", "shared", "Shared", "", "ssh-ed25519", _PUB,
        private_key_local=_PRIV, private_key_vault_ref=None,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    await set_public("shared", True, db_conn)
    rows = await list_certificates("alice", db_conn)
    assert any(r["slug"] == "shared" for r in rows)


async def test_get_private_key(db_conn):
    await _user(db_conn)
    await create_certificate(
        "alice", "k1", "K1", "", "ssh-ed25519", _PUB,
        private_key_local=_PRIV, private_key_vault_ref=None,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    blob = await get_private_key_local("alice", "k1", db_conn)
    assert blob == _PRIV


async def test_get_private_key_public_cert_denied(db_conn):
    await _user(db_conn, "alice")
    await _user(db_conn, "bob")
    await create_certificate(
        "bob", "shared", "S", "", "ssh-ed25519", _PUB,
        private_key_local=_PRIV, private_key_vault_ref=None,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    await set_public("shared", True, db_conn)
    # alice ne peut pas récupérer la clé privée locale d'un cert public qui ne lui appartient pas
    blob = await get_private_key_local("alice", "shared", db_conn)
    assert blob is None


async def test_delete_returns_row(db_conn):
    await _user(db_conn)
    await create_certificate(
        "alice", "k1", "K1", "", "ssh-ed25519", _PUB,
        private_key_local=_PRIV, private_key_vault_ref=None,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    row = await delete_certificate("alice", "k1", db_conn)
    assert row is not None
    assert row["slug"] == "k1"
    assert await list_certificates("alice", db_conn) == []


async def test_delete_nonexistent_returns_none(db_conn):
    await _user(db_conn)
    assert await delete_certificate("alice", "ghost", db_conn) is None
```

- [ ] **Étape 2 : Lancer les tests (vérifier échec)**

```bash
cd backend && uv run pytest tests/db/test_certificates.py -v
```

Résultat attendu : `ImportError: cannot import name 'create_certificate'`

- [ ] **Étape 3 : Implémenter `db/certificates.py`**

```python
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import harpo_certificates


async def create_certificate(
    login: str,
    slug: str,
    label: str,
    description: str,
    cert_type: str,
    public_key: str,
    *,
    private_key_local: bytes | None,
    private_key_vault_ref: str | None,
    storage_type: str,
    vault_identifier: str | None,
    conn: AsyncConnection,
) -> None:
    await conn.execute(
        insert(harpo_certificates).values(
            owner_login=login,
            slug=slug,
            label=label,
            description=description,
            cert_type=cert_type,
            public_key=public_key,
            private_key_local=private_key_local,
            private_key_vault_ref=private_key_vault_ref,
            storage_type=storage_type,
            vault_identifier=vault_identifier,
        )
    )


_PUBLIC_COLS = [
    harpo_certificates.c.slug,
    harpo_certificates.c.label,
    harpo_certificates.c.description,
    harpo_certificates.c.cert_type,
    harpo_certificates.c.public_key,
    harpo_certificates.c.storage_type,
    harpo_certificates.c.vault_identifier,
    harpo_certificates.c.owner_login,
    harpo_certificates.c.is_public,
    harpo_certificates.c.created_at,
]


async def list_certificates(login: str, conn: AsyncConnection) -> list[dict[str, Any]]:
    q = select(*_PUBLIC_COLS).where(
        or_(
            harpo_certificates.c.owner_login == login,
            harpo_certificates.c.is_public.is_(True),
        )
    ).order_by(harpo_certificates.c.created_at)
    rows = (await conn.execute(q)).mappings().all()
    return [dict(r) for r in rows]


async def get_certificate(login: str, slug: str, conn: AsyncConnection) -> dict[str, Any] | None:
    q = select(*_PUBLIC_COLS).where(
        harpo_certificates.c.slug == slug,
        or_(
            harpo_certificates.c.owner_login == login,
            harpo_certificates.c.is_public.is_(True),
        ),
    )
    row = (await conn.execute(q)).mappings().first()
    return dict(row) if row else None


async def get_private_key_local(login: str, slug: str, conn: AsyncConnection) -> bytes | None:
    """Retourne private_key_local uniquement si l'utilisateur est le propriétaire."""
    q = select(harpo_certificates.c.private_key_local).where(
        harpo_certificates.c.slug == slug,
        harpo_certificates.c.owner_login == login,
    )
    row = (await conn.execute(q)).first()
    return row[0] if row else None


async def delete_certificate(
    login: str, slug: str, conn: AsyncConnection
) -> dict[str, Any] | None:
    q = (
        delete(harpo_certificates)
        .where(
            harpo_certificates.c.owner_login == login,
            harpo_certificates.c.slug == slug,
        )
        .returning(*_PUBLIC_COLS, harpo_certificates.c.private_key_vault_ref)
    )
    row = (await conn.execute(q)).mappings().first()
    return dict(row) if row else None


async def set_public(slug: str, is_public: bool, conn: AsyncConnection) -> bool:
    q = (
        update(harpo_certificates)
        .where(harpo_certificates.c.slug == slug)
        .values(is_public=is_public)
        .returning(harpo_certificates.c.slug)
    )
    row = (await conn.execute(q)).first()
    return row is not None
```

- [ ] **Étape 4 : Lancer les tests**

```bash
cd backend && uv run pytest tests/db/test_certificates.py -v
```

Résultat attendu : 6 tests PASSED

- [ ] **Étape 5 : Lint + mypy**

```bash
cd backend && uv run ruff check src/portal/db/certificates.py && uv run mypy src/portal/db/certificates.py
```

- [ ] **Étape 6 : Commit**

```bash
git add backend/src/portal/db/certificates.py backend/tests/db/test_certificates.py
git commit -m "feat(certificates): CRUD DB harpo_certificates"
```

---

## Tâche 3 — Génération de clés server-side

**Fichiers :**
- Créer : `backend/src/portal/certificates/__init__.py`
- Créer : `backend/src/portal/certificates/keygen.py`
- Créer : `backend/tests/certificates/__init__.py`
- Créer : `backend/tests/certificates/test_keygen.py`

**Interfaces produites :**
- `CertType = Literal["ssh-ed25519", "ssh-rsa-2048", "ssh-rsa-4096", "ssh-ecdsa-p256", "tls-rsa-2048", "tls-rsa-4096", "tls-ec-p256", "tls-ec-p384"]`
- `KeyPair(public_key: str, private_key_pem: str)`
- `generate_keypair(cert_type: CertType) -> KeyPair`

- [ ] **Étape 1 : Écrire les tests**

Créer `backend/tests/certificates/test_keygen.py` :

```python
from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat, load_pem_private_key,
    load_ssh_private_key, load_ssh_public_key,
)

from portal.certificates.keygen import CertType, generate_keypair


@pytest.mark.parametrize("cert_type", [
    "ssh-ed25519", "ssh-rsa-2048", "ssh-rsa-4096", "ssh-ecdsa-p256",
])
def test_ssh_keypair_roundtrip(cert_type: CertType):
    kp = generate_keypair(cert_type)
    assert kp.public_key.startswith("ssh-")
    priv = load_ssh_private_key(kp.private_key_pem.encode(), password=None)
    pub = load_ssh_public_key(kp.public_key.encode())
    assert priv.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH) \
           == pub.public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)


@pytest.mark.parametrize("cert_type,expected_cls", [
    ("ssh-ed25519", ed25519.Ed25519PrivateKey),
    ("ssh-rsa-2048", rsa.RSAPrivateKey),
    ("ssh-rsa-4096", rsa.RSAPrivateKey),
    ("ssh-ecdsa-p256", ec.EllipticCurvePrivateKey),
])
def test_ssh_key_type(cert_type: CertType, expected_cls):
    kp = generate_keypair(cert_type)
    priv = load_ssh_private_key(kp.private_key_pem.encode(), password=None)
    assert isinstance(priv, expected_cls)


@pytest.mark.parametrize("cert_type", [
    "tls-rsa-2048", "tls-rsa-4096", "tls-ec-p256", "tls-ec-p384",
])
def test_tls_keypair_pem(cert_type: CertType):
    kp = generate_keypair(cert_type)
    assert "BEGIN PRIVATE KEY" in kp.private_key_pem
    assert "BEGIN PUBLIC KEY" in kp.public_key
    load_pem_private_key(kp.private_key_pem.encode(), password=None)


def test_rsa_2048_key_size():
    kp = generate_keypair("ssh-rsa-2048")
    priv = load_ssh_private_key(kp.private_key_pem.encode(), password=None)
    assert priv.key_size == 2048


def test_rsa_4096_key_size():
    kp = generate_keypair("ssh-rsa-4096")
    priv = load_ssh_private_key(kp.private_key_pem.encode(), password=None)
    assert priv.key_size == 4096
```

- [ ] **Étape 2 : Lancer les tests (vérifier échec)**

```bash
cd backend && uv run pytest tests/certificates/test_keygen.py -v
```

Résultat attendu : `ImportError: No module named 'portal.certificates'`

- [ ] **Étape 3 : Implémenter**

Créer `backend/src/portal/certificates/__init__.py` (vide).

Créer `backend/src/portal/certificates/keygen.py` :

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

CertType = Literal[
    "ssh-ed25519",
    "ssh-rsa-2048",
    "ssh-rsa-4096",
    "ssh-ecdsa-p256",
    "tls-rsa-2048",
    "tls-rsa-4096",
    "tls-ec-p256",
    "tls-ec-p384",
]

_SSH_TYPES = {"ssh-ed25519", "ssh-rsa-2048", "ssh-rsa-4096", "ssh-ecdsa-p256"}


@dataclass(frozen=True)
class KeyPair:
    public_key: str    # OpenSSH ou PEM SubjectPublicKeyInfo
    private_key_pem: str  # OpenSSH PEM ou PKCS8 PEM (jamais chiffré)


def generate_keypair(cert_type: CertType) -> KeyPair:
    if cert_type == "ssh-ed25519":
        priv = ed25519.Ed25519PrivateKey.generate()
    elif cert_type == "ssh-rsa-2048":
        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    elif cert_type == "ssh-rsa-4096":
        priv = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    elif cert_type == "ssh-ecdsa-p256":
        priv = ec.generate_private_key(ec.SECP256R1())
    elif cert_type == "tls-rsa-2048":
        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    elif cert_type == "tls-rsa-4096":
        priv = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    elif cert_type == "tls-ec-p256":
        priv = ec.generate_private_key(ec.SECP256R1())
    elif cert_type == "tls-ec-p384":
        priv = ec.generate_private_key(ec.SECP384R1())
    else:
        raise ValueError(f"Unknown cert_type: {cert_type}")

    if cert_type in _SSH_TYPES:
        private_pem = priv.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption())
        public_bytes = priv.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)
    else:
        private_pem = priv.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        public_bytes = priv.public_key().public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
        )

    return KeyPair(
        public_key=public_bytes.decode(),
        private_key_pem=private_pem.decode(),
    )
```

- [ ] **Étape 4 : Lancer les tests**

```bash
cd backend && uv run pytest tests/certificates/test_keygen.py -v
```

Résultat attendu : 10 tests PASSED

- [ ] **Étape 5 : Lint + mypy**

```bash
cd backend && uv run ruff check src/portal/certificates/ && uv run mypy src/portal/certificates/
```

- [ ] **Étape 6 : Commit**

```bash
git add backend/src/portal/certificates/ backend/tests/certificates/
git commit -m "feat(certificates): génération server-side paires de clés SSH/TLS"
```

---

## Tâche 4 — Service métier

**Fichiers :**
- Créer : `backend/src/portal/certificates/service.py`
- Créer : `backend/tests/certificates/test_service.py`

**Interfaces consommées :**
- `generate_keypair(cert_type) -> KeyPair` (Tâche 3)
- `create_certificate(...)`, `list_certificates(...)`, `get_certificate(...)`, `get_private_key_local(...)`, `delete_certificate(...)` (Tâche 2)
- `encrypt_token(token: str, master_key: bytes) -> bytes` depuis `portal.vault.crypto`
- `decrypt_token(encrypted: bytes, master_key: bytes) -> str` depuis `portal.vault.crypto`
- `get_vault_client(login, session_id, identifier, conn)` depuis `portal.vault.keys`
- `get_master_key(session_id) -> bytes | None` depuis `portal.vault.session`

**Interfaces produites :**
- `class CertNotFound(Exception)`
- `class CertAlreadyExists(Exception)`
- `class VaultLocked(Exception)`
- `register_certificate(login, session_id, slug, label, description, cert_type, public_key, private_key_pem, storage_type, vault_identifier, conn) -> None`
- `generate_and_register(login, session_id, slug, label, description, cert_type, storage_type, vault_identifier, conn) -> str` → retourne la clé publique
- `list_user_certificates(login, conn) -> list[dict]`
- `reveal_private_key(login, session_id, slug, conn) -> str` → PEM déchiffré
- `remove_certificate(login, session_id, slug, conn) -> None` → supprime DB + harpocrate si besoin

- [ ] **Étape 1 : Écrire les tests**

Créer `backend/tests/certificates/test_service.py` :

```python
from __future__ import annotations

import uuid
import pytest
from sqlalchemy import insert
from portal.db.tables import users
from portal.certificates.service import (
    CertAlreadyExists,
    CertNotFound,
    VaultLocked,
    generate_and_register,
    list_user_certificates,
    register_certificate,
    remove_certificate,
    reveal_private_key,
)
from portal.vault import session as vault_session

pytestmark = pytest.mark.asyncio

_PUB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5 test"
_PRIV = "-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----\n"
_SID = "test-session-123"
_MASTER = b"\x01" * 32


async def _user(conn, login: str = "alice") -> None:
    await conn.execute(insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4())))


async def test_register_local_and_list(db_conn):
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)
    await register_certificate(
        "alice", _SID, "gh", "GitHub", "", "ssh-ed25519", _PUB, _PRIV,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    certs = await list_user_certificates("alice", db_conn)
    assert len(certs) == 1
    assert certs[0]["slug"] == "gh"
    assert "private_key_local" not in certs[0]


async def test_register_duplicate_raises(db_conn):
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)
    await register_certificate(
        "alice", _SID, "gh", "GitHub", "", "ssh-ed25519", _PUB, _PRIV,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    with pytest.raises(CertAlreadyExists):
        await register_certificate(
            "alice", _SID, "gh", "GitHub2", "", "ssh-ed25519", _PUB, _PRIV,
            storage_type="local", vault_identifier=None, conn=db_conn,
        )


async def test_register_vault_locked_raises(db_conn):
    await _user(db_conn)
    vault_session.clear_session("no-session")
    with pytest.raises(VaultLocked):
        await register_certificate(
            "alice", "no-session", "gh", "GitHub", "", "ssh-ed25519", _PUB, _PRIV,
            storage_type="local", vault_identifier=None, conn=db_conn,
        )


async def test_reveal_private_key(db_conn):
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)
    await register_certificate(
        "alice", _SID, "gh", "GitHub", "", "ssh-ed25519", _PUB, _PRIV,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    plain = await reveal_private_key("alice", _SID, "gh", db_conn)
    assert plain == _PRIV


async def test_reveal_vault_locked(db_conn):
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)
    await register_certificate(
        "alice", _SID, "gh", "GitHub", "", "ssh-ed25519", _PUB, _PRIV,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    vault_session.clear_session(_SID)
    with pytest.raises(VaultLocked):
        await reveal_private_key("alice", _SID, "gh", db_conn)


async def test_generate_and_register(db_conn):
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)
    pub = await generate_and_register(
        "alice", _SID, "new-key", "New Key", "", "ssh-ed25519",
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    assert pub.startswith("ssh-ed25519")
    certs = await list_user_certificates("alice", db_conn)
    assert certs[0]["slug"] == "new-key"


async def test_remove_certificate(db_conn):
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)
    await register_certificate(
        "alice", _SID, "gh", "GitHub", "", "ssh-ed25519", _PUB, _PRIV,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    await remove_certificate("alice", _SID, "gh", db_conn)
    assert await list_user_certificates("alice", db_conn) == []


async def test_remove_nonexistent_raises(db_conn):
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)
    with pytest.raises(CertNotFound):
        await remove_certificate("alice", _SID, "ghost", db_conn)
```

- [ ] **Étape 2 : Lancer les tests (vérifier échec)**

```bash
cd backend && uv run pytest tests/certificates/test_service.py -v
```

Résultat attendu : `ImportError`

- [ ] **Étape 3 : Implémenter `service.py`**

```python
from __future__ import annotations

import anyio
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db.certificates import (
    create_certificate,
    delete_certificate,
    get_private_key_local,
    list_certificates,
)
from ..vault import session as vault_session
from ..vault.crypto import decrypt_token, encrypt_token
from ..vault.keys import get_vault_client
from .keygen import CertType, generate_keypair

_log = structlog.get_logger(__name__)

_VAULT_PATH_PRIVATE = "certificats/{slug}/private"
_VAULT_PATH_PUBLIC = "certificats/{slug}/public"


class VaultLocked(Exception):
    pass


class CertAlreadyExists(Exception):
    pass


class CertNotFound(Exception):
    pass


def _require_master_key(session_id: str) -> bytes:
    mk = vault_session.get_master_key(session_id)
    if mk is None:
        raise VaultLocked("Vault verrouillé — déverrouillez avec votre PIN")
    return mk


async def register_certificate(
    login: str,
    session_id: str,
    slug: str,
    label: str,
    description: str,
    cert_type: str,
    public_key: str,
    private_key_pem: str,
    *,
    storage_type: str,
    vault_identifier: str | None,
    conn: AsyncConnection,
) -> None:
    master_key = _require_master_key(session_id)

    if storage_type == "local":
        encrypted = encrypt_token(private_key_pem, master_key)
        vault_ref = None
        _write_harpocrate = None
    else:
        encrypted = None
        vault_ref = "${vault://" + vault_identifier + ":certificats/" + slug + "/private}"
        client = await get_vault_client(login, session_id, vault_identifier, conn)
        _write_harpocrate = (client, slug, public_key, private_key_pem)

    try:
        await create_certificate(
            login, slug, label, description, cert_type, public_key,
            private_key_local=encrypted,
            private_key_vault_ref=vault_ref,
            storage_type=storage_type,
            vault_identifier=vault_identifier,
            conn=conn,
        )
    except IntegrityError as exc:
        raise CertAlreadyExists(f"Un certificat '{slug}' existe déjà") from exc

    if _write_harpocrate:
        client, slug_, pub, priv = _write_harpocrate
        await anyio.to_thread.run_sync(
            lambda: client.secrets.create(_VAULT_PATH_PUBLIC.format(slug=slug_), pub)
        )
        await anyio.to_thread.run_sync(
            lambda: client.secrets.create(_VAULT_PATH_PRIVATE.format(slug=slug_), priv)
        )
    _log.info("certificate_registered", login=login, slug=slug, storage_type=storage_type)


async def generate_and_register(
    login: str,
    session_id: str,
    slug: str,
    label: str,
    description: str,
    cert_type: CertType,
    *,
    storage_type: str,
    vault_identifier: str | None,
    conn: AsyncConnection,
) -> str:
    kp = await anyio.to_thread.run_sync(lambda: generate_keypair(cert_type))
    await register_certificate(
        login, session_id, slug, label, description, cert_type,
        kp.public_key, kp.private_key_pem,
        storage_type=storage_type,
        vault_identifier=vault_identifier,
        conn=conn,
    )
    return kp.public_key


async def list_user_certificates(login: str, conn: AsyncConnection) -> list[dict]:
    return await list_certificates(login, conn)


async def reveal_private_key(
    login: str, session_id: str, slug: str, conn: AsyncConnection
) -> str:
    master_key = _require_master_key(session_id)
    blob = await get_private_key_local(login, slug, conn)
    if blob is not None:
        return decrypt_token(blob, master_key)
    # Cas harpocrate : récupère via SDK
    from ..db.certificates import get_certificate
    row = await get_certificate(login, slug, conn)
    if row is None:
        raise CertNotFound(f"Certificat '{slug}' introuvable")
    if row["storage_type"] != "harpocrate" or row["owner_login"] != login:
        raise CertNotFound("Clé privée inaccessible")
    client = await get_vault_client(login, session_id, row["vault_identifier"], conn)
    return await anyio.to_thread.run_sync(
        lambda: client.secrets.get(_VAULT_PATH_PRIVATE.format(slug=slug))
    )


async def remove_certificate(
    login: str, session_id: str, slug: str, conn: AsyncConnection
) -> None:
    _require_master_key(session_id)
    row = await delete_certificate(login, slug, conn)
    if row is None:
        raise CertNotFound(f"Certificat '{slug}' introuvable ou non autorisé")
    if row["storage_type"] == "harpocrate" and row.get("vault_identifier"):
        client = await get_vault_client(login, session_id, row["vault_identifier"], conn)
        for path in (
            _VAULT_PATH_PRIVATE.format(slug=slug),
            _VAULT_PATH_PUBLIC.format(slug=slug),
        ):
            try:
                await anyio.to_thread.run_sync(lambda p=path: client.secrets.delete(p))
            except Exception:
                _log.warning("cert_vault_delete_failed", slug=slug, path=path)
    _log.info("certificate_removed", login=login, slug=slug)
```

- [ ] **Étape 4 : Lancer les tests**

```bash
cd backend && uv run pytest tests/certificates/test_service.py -v
```

Résultat attendu : 8 tests PASSED

- [ ] **Étape 5 : Lint + mypy**

```bash
cd backend && uv run ruff check src/portal/certificates/service.py && uv run mypy src/portal/certificates/service.py
```

- [ ] **Étape 6 : Commit**

```bash
git add backend/src/portal/certificates/service.py backend/tests/certificates/test_service.py
git commit -m "feat(certificates): service métier (register, generate, reveal, remove)"
```

---

## Tâche 5 — Routes FastAPI + enregistrement

**Fichiers :**
- Créer : `backend/src/portal/routes/certificates.py`
- Modifier : `backend/src/portal/app.py`

**Interfaces consommées :**
- `register_certificate(...)`, `generate_and_register(...)`, `list_user_certificates(...)`, `reveal_private_key(...)`, `remove_certificate(...)` (Tâche 4)
- `CertAlreadyExists`, `CertNotFound`, `VaultLocked` (Tâche 4)
- `require_user`, `require_admin` depuis `portal.auth.rbac`
- `get_conn` depuis `portal.db.engine`
- `set_public` depuis `portal.db.certificates`

**Interfaces produites :**
- `GET /me/certificates` → `list[CertDTO]`
- `POST /me/certificates/generate` → `{public_key: str}`
- `POST /me/certificates` → `{slug: str}`
- `GET /me/certificates/{slug}/private` → `{private_key_pem: str}`
- `DELETE /me/certificates/{slug}` → 204
- `PATCH /admin/certificates/{slug}/visibility` → `{is_public: bool}`

- [ ] **Étape 1 : Implémenter les routes**

Créer `backend/src/portal/routes/certificates.py` :

```python
from __future__ import annotations

import re
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin, require_user
from ..certificates.service import (
    CertAlreadyExists,
    CertNotFound,
    VaultLocked,
    generate_and_register,
    list_user_certificates,
    register_certificate,
    remove_certificate,
    reveal_private_key,
)
from ..db.certificates import set_public
from ..db.engine import get_conn

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["certificates"])

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")

CERT_TYPES = Literal[
    "ssh-ed25519", "ssh-rsa-2048", "ssh-rsa-4096", "ssh-ecdsa-p256",
    "tls-rsa-2048", "tls-rsa-4096", "tls-ec-p256", "tls-ec-p384",
]


def _sid(request: Request) -> str:
    return str(request.session.get("session_id", ""))


class GenerateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    label: str
    description: str = ""
    cert_type: CERT_TYPES
    storage_type: Literal["local", "harpocrate"] = "local"
    vault_identifier: str | None = None

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not _SLUG_RE.fullmatch(v):
            raise ValueError("slug: lowercase alphanum + tirets/underscores")
        return v


class RegisterBody(GenerateBody):
    public_key: str
    private_key_pem: str


class VisibilityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_public: bool


def _handle_common(exc: Exception) -> None:
    if isinstance(exc, VaultLocked):
        raise HTTPException(403, "vault_locked") from exc
    if isinstance(exc, CertAlreadyExists):
        raise HTTPException(409, str(exc)) from exc
    if isinstance(exc, CertNotFound):
        raise HTTPException(404, str(exc)) from exc


@router.get("/certificates")
async def list_certs(
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    return await list_user_certificates(user.login, conn)


@router.post("/certificates/generate")
async def generate_cert(
    body: GenerateBody,
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        pub = await generate_and_register(
            user.login, _sid(request), body.slug, body.label, body.description,
            body.cert_type,
            storage_type=body.storage_type,
            vault_identifier=body.vault_identifier,
            conn=conn,
        )
    except Exception as exc:
        _handle_common(exc)
        raise
    return {"public_key": pub, "slug": body.slug}


@router.post("/certificates")
async def register_cert(
    body: RegisterBody,
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        await register_certificate(
            user.login, _sid(request), body.slug, body.label, body.description,
            body.cert_type, body.public_key, body.private_key_pem,
            storage_type=body.storage_type,
            vault_identifier=body.vault_identifier,
            conn=conn,
        )
    except Exception as exc:
        _handle_common(exc)
        raise
    return {"slug": body.slug}


@router.get("/certificates/{slug}/private")
async def get_private(
    slug: str,
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        pem = await reveal_private_key(user.login, _sid(request), slug, conn)
    except Exception as exc:
        _handle_common(exc)
        raise
    return {"private_key_pem": pem}


@router.delete("/certificates/{slug}", status_code=204)
async def delete_cert(
    slug: str,
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    try:
        await remove_certificate(user.login, _sid(request), slug, conn)
    except Exception as exc:
        _handle_common(exc)
        raise


@router.patch("/admin/certificates/{slug}/visibility")
async def set_visibility(
    slug: str,
    body: VisibilityBody,
    _user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    ok = await set_public(slug, body.is_public, conn)
    if not ok:
        raise HTTPException(404, f"Certificat '{slug}' introuvable")
    return {"slug": slug, "is_public": body.is_public}
```

- [ ] **Étape 2 : Enregistrer le router dans `app.py`**

Dans `backend/src/portal/app.py`, ajouter l'import :

```python
from .routes.certificates import router as certificates_router
```

Et dans `create_app()`, après `app.include_router(vault_router)` :

```python
app.include_router(certificates_router, prefix="/me")
app.include_router(certificates_router, prefix="/admin", tags=["admin-certificates"])
```

Attention : les routes admin (`/admin/certificates/{slug}/visibility`) et user (`/me/certificates/...`) sont dans le même router. Pour éviter le conflit, séparer en deux routers ou utiliser des préfixes distincts dans les routes elles-mêmes. Plus simple : garder un seul `router` avec les chemins déjà distincts (`/certificates/...` vs `/admin/certificates/...`) et l'enregistrer sans préfixe, puis ajouter le préfixe `/me` uniquement aux routes user.

Approche propre — **deux routers dans `routes/certificates.py`** :

```python
router_me = APIRouter(tags=["certificates"])     # préfixé /me
router_admin = APIRouter(tags=["certificates"])  # préfixé /admin
```

Déplacer les routes user dans `router_me` et la route visibility dans `router_admin`.

Dans `app.py` :

```python
from .routes.certificates import router_admin as certs_admin_router
from .routes.certificates import router_me as certs_me_router
# ...
app.include_router(certs_me_router, prefix="/me")
app.include_router(certs_admin_router, prefix="/admin")
```

- [ ] **Étape 3 : Vérifier le démarrage**

```bash
cd backend && uv run uvicorn portal.app:app --reload &
sleep 3 && curl -s http://localhost:8080/openapi.json | python3 -c "
import json,sys; [print(p) for p in json.load(sys.stdin)['paths'] if 'certificate' in p]
"
```

Résultat attendu : liste des 6 routes `/me/certificates/...` et `/admin/certificates/...`

- [ ] **Étape 4 : Lint + mypy**

```bash
cd backend && uv run ruff check src/portal/routes/certificates.py && uv run mypy src/portal/routes/certificates.py
```

- [ ] **Étape 5 : Commit**

```bash
git add backend/src/portal/routes/certificates.py backend/src/portal/app.py
git commit -m "feat(certificates): routes FastAPI /me/certificates + /admin/certificates"
```

---

## Tâche 6 — Frontend : API hooks

**Fichiers :**
- Créer : `frontend/src/features/certificates/api.ts`

**Interfaces produites :**
- `CertType` (union string)
- `Certificate` (interface)
- `useCertificates()` → `UseQueryResult<Certificate[]>`
- `useGenerateCertificate()` → mutation
- `useRegisterCertificate()` → mutation
- `useDeleteCertificate()` → mutation
- `useRevealPrivateKey()` → mutation (POST pour ne pas logger en URL)
- `useSetCertVisibility()` → mutation (admin)

- [ ] **Étape 1 : Implémenter `api.ts`**

```typescript
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, apiFetchJson } from '@/shared/api/client'

export type CertType =
  | 'ssh-ed25519' | 'ssh-rsa-2048' | 'ssh-rsa-4096' | 'ssh-ecdsa-p256'
  | 'tls-rsa-2048' | 'tls-rsa-4096' | 'tls-ec-p256' | 'tls-ec-p384'

export interface Certificate {
  slug: string
  label: string
  description: string
  cert_type: CertType
  public_key: string
  storage_type: 'local' | 'harpocrate'
  vault_identifier: string | null
  owner_login: string
  is_public: boolean
  is_own: boolean
  created_at: string
}

export interface GenerateBody {
  slug: string
  label: string
  description?: string
  cert_type: CertType
  storage_type: 'local' | 'harpocrate'
  vault_identifier?: string | null
}

export interface RegisterBody extends GenerateBody {
  public_key: string
  private_key_pem: string
}

const QK = {
  list: () => ['certificates'] as const,
}

export function useCertificates() {
  return useQuery({
    queryKey: QK.list(),
    queryFn: () => apiFetchJson<Certificate[]>('/me/certificates'),
  })
}

export function useGenerateCertificate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: GenerateBody) =>
      apiFetchJson<{ public_key: string; slug: string }>('/me/certificates/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.list() }),
  })
}

export function useRegisterCertificate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: RegisterBody) =>
      apiFetchJson<{ slug: string }>('/me/certificates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.list() }),
  })
}

export function useDeleteCertificate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (slug: string) =>
      apiFetch(`/me/certificates/${encodeURIComponent(slug)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.list() }),
  })
}

export function useRevealPrivateKey() {
  return useMutation({
    mutationFn: (slug: string) =>
      apiFetchJson<{ private_key_pem: string }>(
        `/me/certificates/${encodeURIComponent(slug)}/private`,
      ),
  })
}

export function useSetCertVisibility() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ slug, is_public }: { slug: string; is_public: boolean }) =>
      apiFetchJson<{ slug: string; is_public: boolean }>(
        `/admin/certificates/${encodeURIComponent(slug)}/visibility`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ is_public }),
        },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.list() }),
  })
}
```

- [ ] **Étape 2 : Typecheck**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep certificates
```

Résultat attendu : aucune erreur sur `certificates/api.ts`

- [ ] **Étape 3 : Commit**

```bash
git add frontend/src/features/certificates/api.ts
git commit -m "feat(certificates): hooks TanStack Query"
```

---

## Tâche 7 — Frontend : onglet CertificatesTab + i18n

**Fichiers :**
- Créer : `frontend/src/features/certificates/CertificatesTab.tsx`
- Modifier : `frontend/src/features/git-credentials/CredentialsPage.tsx`
- Modifier : `frontend/src/i18n/fr.json`
- Modifier : `frontend/src/i18n/en.json`

**Interfaces consommées :** Tous les hooks de Tâche 6.

- [ ] **Étape 1 : Ajouter les clés i18n**

Dans `frontend/src/i18n/fr.json`, ajouter la section `certificates` :

```json
"certificates": {
  "tabLabel": "Certificats",
  "title": "Certificats & Clés",
  "info": "Gérez vos paires de clés SSH et certificats TLS. Les clés privées sont chiffrées avec votre PIN vault.",
  "addKey": "Ajouter",
  "generateKey": "Générer",
  "noKeys": "Aucun certificat enregistré.",
  "publicBadge": "Public",
  "ownedBy": "Propriétaire : {{login}}",
  "dialogGenerateTitle": "Générer une paire de clés",
  "dialogRegisterTitle": "Enregistrer une paire de clés",
  "revealPrivate": "Révéler la clé privée",
  "privateKeyLabel": "Clé privée",
  "publicKeyLabel": "Clé publique",
  "copied": "Copié !",
  "copy": "Copier",
  "confirmDelete": "Confirmer la suppression",
  "makePublic": "Rendre public",
  "makePrivate": "Rendre privé",
  "form": {
    "label": "Nom",
    "labelPlaceholder": "ex : GitHub SSH",
    "slug": "Identifiant (slug)",
    "slugEmpty": "auto",
    "description": "Description",
    "descriptionPlaceholder": "À quoi sert cette clé ?",
    "certType": "Type",
    "storageType": "Stockage",
    "storageLocal": "Local (chiffré dans la base)",
    "storageHarpocrate": "Wallet Harpocrate",
    "vaultWallet": "Wallet",
    "privateKey": "Clé privée (PEM)",
    "publicKey": "Clé publique",
    "pasteMode": "Coller",
    "generateMode": "Générer",
    "generating": "Génération...",
    "saving": "Enregistrement...",
    "save": "Enregistrer"
  }
}
```

Dans `frontend/src/i18n/en.json`, ajouter la section `certificates` (valeurs anglaises équivalentes).

- [ ] **Étape 2 : Implémenter `CertificatesTab.tsx`**

```tsx
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { KeyRound, Plus, Eye, EyeOff, Copy, Check, Pencil } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import {
  useCertificates, useGenerateCertificate, useRegisterCertificate,
  useDeleteCertificate, useRevealPrivateKey,
  type Certificate, type CertType, type GenerateBody,
} from './api'
import { useVaultKeys } from '@/features/vault/api'

const CERT_TYPES: { value: CertType; label: string }[] = [
  { value: 'ssh-ed25519', label: 'SSH Ed25519 (recommandé)' },
  { value: 'ssh-rsa-2048', label: 'SSH RSA 2048' },
  { value: 'ssh-rsa-4096', label: 'SSH RSA 4096' },
  { value: 'ssh-ecdsa-p256', label: 'SSH ECDSA P-256' },
  { value: 'tls-rsa-2048', label: 'TLS RSA 2048' },
  { value: 'tls-rsa-4096', label: 'TLS RSA 4096' },
  { value: 'tls-ec-p256', label: 'TLS EC P-256' },
  { value: 'tls-ec-p384', label: 'TLS EC P-384' },
]

function slugify(label: string): string {
  return label.trim().toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+/, '').replace(/-+$/, '')
    .slice(0, 63)
}

function CopyButton({ text }: { text: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  function copy() {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <Button size="sm" variant="ghost" onClick={copy}>
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      {copied ? t('certificates.copied') : t('certificates.copy')}
    </Button>
  )
}

interface AddDialogProps {
  open: boolean
  onClose: () => void
}

function AddDialog({ open, onClose }: AddDialogProps) {
  const { t } = useTranslation()
  const { data: vaultKeys = [] } = useVaultKeys()
  const generate = useGenerateCertificate()
  const register = useRegisterCertificate()

  const [mode, setMode] = useState<'generate' | 'paste'>('generate')
  const [label, setLabel] = useState('')
  const [description, setDescription] = useState('')
  const [certType, setCertType] = useState<CertType>('ssh-ed25519')
  const [storage, setStorage] = useState<'local' | 'harpocrate'>('local')
  const [vaultId, setVaultId] = useState('')
  const [pubKey, setPubKey] = useState('')
  const [privKey, setPrivKey] = useState('')
  const [generatedPub, setGeneratedPub] = useState('')

  const slug = slugify(label)
  const isPending = generate.isPending || register.isPending

  function reset() {
    setLabel(''); setDescription(''); setCertType('ssh-ed25519')
    setStorage('local'); setVaultId(''); setPubKey(''); setPrivKey(''); setGeneratedPub('')
    generate.reset(); register.reset()
  }

  function close() { reset(); onClose() }

  async function handleGenerate() {
    if (!slug) return
    const body: GenerateBody = {
      slug, label, description, cert_type: certType,
      storage_type: storage,
      vault_identifier: storage === 'harpocrate' ? vaultId : null,
    }
    generate.mutate(body, {
      onSuccess: (r) => { setGeneratedPub(r.public_key); close() },
    })
  }

  async function handlePaste() {
    if (!slug || !pubKey || !privKey) return
    register.mutate(
      {
        slug, label, description, cert_type: certType,
        public_key: pubKey, private_key_pem: privKey,
        storage_type: storage,
        vault_identifier: storage === 'harpocrate' ? vaultId : null,
      },
      { onSuccess: close },
    )
  }

  const error = generate.error ?? register.error
  const canSubmit = !!slug && !isPending && (mode === 'generate' || (!!pubKey && !!privKey))

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) close() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {mode === 'generate' ? t('certificates.dialogGenerateTitle') : t('certificates.dialogRegisterTitle')}
          </DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          {/* Mode switch */}
          <div className="flex gap-2">
            <Button size="sm" variant={mode === 'generate' ? 'default' : 'outline'} onClick={() => setMode('generate')}>
              {t('certificates.form.generateMode')}
            </Button>
            <Button size="sm" variant={mode === 'paste' ? 'default' : 'outline'} onClick={() => setMode('paste')}>
              {t('certificates.form.pasteMode')}
            </Button>
          </div>

          <div className="flex gap-3">
            <div className="flex flex-1 flex-col gap-1.5">
              <Label>{t('certificates.form.label')}</Label>
              <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder={t('certificates.form.labelPlaceholder')} />
            </div>
            <div className="flex flex-1 flex-col gap-1.5">
              <Label>{t('certificates.form.slug')}</Label>
              <div className="flex h-9 items-center rounded-md border bg-muted px-3 font-mono text-sm text-muted-foreground">
                {slug || <span className="italic opacity-50">{t('certificates.form.slugEmpty')}</span>}
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>{t('certificates.form.description')}</Label>
            <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder={t('certificates.form.descriptionPlaceholder')} />
          </div>

          <div className="flex gap-3">
            <div className="flex flex-1 flex-col gap-1.5">
              <Label>{t('certificates.form.certType')}</Label>
              <Select value={certType} onValueChange={(v) => setCertType(v as CertType)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {CERT_TYPES.map((t) => (
                    <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-1 flex-col gap-1.5">
              <Label>{t('certificates.form.storageType')}</Label>
              <Select value={storage} onValueChange={(v) => setStorage(v as 'local' | 'harpocrate')}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="local">{t('certificates.form.storageLocal')}</SelectItem>
                  <SelectItem value="harpocrate" disabled={vaultKeys.length === 0}>
                    {t('certificates.form.storageHarpocrate')}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {storage === 'harpocrate' && (
            <div className="flex flex-col gap-1.5">
              <Label>{t('certificates.form.vaultWallet')}</Label>
              <Select value={vaultId} onValueChange={setVaultId}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {vaultKeys.map((k) => (
                    <SelectItem key={k.identifier} value={k.identifier}>{k.identifier}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {mode === 'paste' && (
            <>
              <div className="flex flex-col gap-1.5">
                <Label>{t('certificates.form.publicKey')}</Label>
                <Textarea rows={2} value={pubKey} onChange={(e) => setPubKey(e.target.value)} className="font-mono text-xs" />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>{t('certificates.form.privateKey')}</Label>
                <Textarea rows={4} value={privKey} onChange={(e) => setPrivKey(e.target.value)} className="font-mono text-xs" />
              </div>
            </>
          )}

          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error instanceof Error ? error.message : t('errors.generic')}</AlertDescription>
            </Alert>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={close}>{t('common.cancel')}</Button>
          <Button
            onClick={mode === 'generate' ? handleGenerate : handlePaste}
            disabled={!canSubmit}
          >
            {isPending
              ? (mode === 'generate' ? t('certificates.form.generating') : t('certificates.form.saving'))
              : (mode === 'generate' ? t('certificates.generateKey') : t('certificates.form.save'))}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function CertRow({ cert }: { cert: Certificate }) {
  const { t } = useTranslation()
  const deleteC = useDeleteCertificate()
  const reveal = useRevealPrivateKey()
  const [showPrivate, setShowPrivate] = useState(false)
  const [privateKey, setPrivateKey] = useState<string | null>(null)
  const [confirmDel, setConfirmDel] = useState(false)

  async function toggleReveal() {
    if (privateKey) { setShowPrivate((v) => !v); return }
    reveal.mutate(cert.slug, {
      onSuccess: (r) => { setPrivateKey(r.private_key_pem); setShowPrivate(true) },
    })
  }

  const isOwn = cert.is_own ?? cert.owner_login !== undefined

  return (
    <div className="flex flex-col gap-2 rounded-lg border bg-card p-3">
      <div className="flex items-center gap-2">
        <KeyRound className="h-4 w-4 shrink-0 text-muted-foreground" />
        <span className="flex-1 font-medium">{cert.label}</span>
        <Badge variant="outline" className="font-mono text-xs">{cert.cert_type}</Badge>
        {cert.is_public && <Badge variant="secondary">{t('certificates.publicBadge')}</Badge>}
      </div>
      {cert.description && <p className="text-xs text-muted-foreground">{cert.description}</p>}
      <div className="flex items-center gap-1 rounded bg-muted/50 p-2 font-mono text-xs break-all">
        <span className="flex-1 select-all">{cert.public_key}</span>
        <CopyButton text={cert.public_key} />
      </div>
      {showPrivate && privateKey && (
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">{t('certificates.privateKeyLabel')}</span>
          <div className="flex items-start gap-1 rounded bg-muted/50 p-2 font-mono text-xs break-all">
            <pre className="flex-1 whitespace-pre-wrap select-all">{privateKey}</pre>
            <CopyButton text={privateKey} />
          </div>
        </div>
      )}
      <div className="flex gap-2">
        {cert.storage_type === 'local' && (
          <Button size="sm" variant="outline" onClick={toggleReveal} disabled={reveal.isPending}>
            {showPrivate ? <EyeOff className="mr-1 h-3.5 w-3.5" /> : <Eye className="mr-1 h-3.5 w-3.5" />}
            {t('certificates.revealPrivate')}
          </Button>
        )}
        {cert.owner_login === cert.owner_login && (
          confirmDel ? (
            <div className="flex gap-1">
              <Button size="sm" variant="destructive" disabled={deleteC.isPending}
                onClick={() => deleteC.mutate(cert.slug, { onSuccess: () => setConfirmDel(false) })}>
                {t('certificates.confirmDelete')}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirmDel(false)}>{t('common.cancel')}</Button>
            </div>
          ) : (
            <Button size="sm" variant="ghost" className="text-destructive hover:text-destructive"
              onClick={() => setConfirmDel(true)}>
              {t('workspaces.actions.delete')}
            </Button>
          )
        )}
      </div>
    </div>
  )
}

export default function CertificatesTab() {
  const { t } = useTranslation()
  const { data: certs = [], isLoading } = useCertificates()
  const [addOpen, setAddOpen] = useState(false)

  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-lg border bg-muted/40 p-5">
        <div className="mb-2 flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-semibold">{t('certificates.title')}</span>
        </div>
        <p className="text-sm text-muted-foreground leading-relaxed">{t('certificates.info')}</p>
      </div>

      <div className="flex items-center justify-between">
        <h2 className="font-medium">{t('certificates.tabLabel')}</h2>
        <Button size="sm" onClick={() => setAddOpen(true)}>
          <Plus className="mr-1 h-4 w-4" />
          {t('certificates.addKey')}
        </Button>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {!isLoading && certs.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('certificates.noKeys')}</p>
      )}
      <div className="flex flex-col gap-3">
        {certs.map((c) => <CertRow key={`${c.owner_login}/${c.slug}`} cert={c} />)}
      </div>

      <AddDialog open={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  )
}
```

- [ ] **Étape 3 : Ajouter l'onglet dans `CredentialsPage.tsx`**

```tsx
import CertificatesTab from '@/features/certificates/CertificatesTab'

export default function CredentialsPage() {
  const { t } = useTranslation()
  return (
    <Tabs defaultValue="vault" className="flex flex-col gap-4">
      <TabsList className="self-start">
        <TabsTrigger value="vault">{t('vault.tabLabel')}</TabsTrigger>
        <TabsTrigger value="certificates">{t('certificates.tabLabel')}</TabsTrigger>
        <TabsTrigger value="git">{t('gitCredentials.title')}</TabsTrigger>
      </TabsList>
      <TabsContent value="vault" className="mt-0"><VaultTab /></TabsContent>
      <TabsContent value="certificates" className="mt-0"><CertificatesTab /></TabsContent>
      <TabsContent value="git" className="mt-0"><GitCredentialManager /></TabsContent>
    </Tabs>
  )
}
```

- [ ] **Étape 4 : Typecheck frontend**

```bash
cd frontend && npx tsc --noEmit
```

Résultat attendu : 0 erreur

- [ ] **Étape 5 : Commit**

```bash
git add frontend/src/features/certificates/ frontend/src/features/git-credentials/CredentialsPage.tsx frontend/src/i18n/
git commit -m "feat(certificates): onglet Certificats UI (generate, paste, reveal, delete)"
```

---

## Auto-vérification spec

| Exigence | Tâche |
|---|---|
| Types SSH ed25519, rsa-2048/4096, ecdsa-p256 | Tâche 3 |
| Types TLS rsa-2048/4096, ec-p256/p384 | Tâche 3 |
| Génération server-side | Tâche 3 + 4 |
| Coller clé publique + privée | Tâche 5 + 7 |
| Chiffrement local `private_key_local` avec master_key | Tâche 4 |
| Stockage harpocrate `certificats/<slug>/private` et `/public` | Tâche 4 |
| Référence `${vault://id:certificats/slug/private}` en DB | Tâche 4 |
| Sélecteur wallet parmi les clés vault de l'utilisateur | Tâche 7 |
| PIN vault requis (local + harpocrate) | Tâche 4 (`_require_master_key`) |
| Visibilité : propres certs + publics admin | Tâche 2 (`list_certificates`) |
| Toggle `is_public` admin | Tâche 5 + 6 |
| Bouton Révéler clé privée | Tâche 7 |
| Onglet Vault → Certificats → Git Credentials | Tâche 7 |
| Clé privée jamais dans les logs | Tâche 4 (aucun log de la valeur) |
| Suppression harpocrate nettoyée | Tâche 4 (`remove_certificate`) |
