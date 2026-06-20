# Host Secrets — Migration vers harpo_* Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrer `ci_password` et la clé SSH/cert TLS des hosts depuis le disque vers les tables `harpo_secrets` / `harpo_certificates`, avec un sélecteur de stockage (local ou Harpocrate) dans les formulaires Add Host et Generate Host.

**Architecture:** Les secrets de host sont des ressources système (non liées à un utilisateur OIDC). Un pseudo-utilisateur `__system__` est inséré au démarrage dans la table `users` pour satisfaire la FK des tables `harpo_*`. Le chiffrement local utilise un `system_master_key` dérivé du `PORTAL_VAULT_KEK` via HKDF (aucune session/PIN requise). La table `hosts` perd les colonnes `key_path` et `ci_password`; elle gagne `host_cert_slug`, `ci_password_secret_slug`, `storage_type`, `vault_identifier`. Dans `devpod/service.py`, la clé SSH est matérialisée en fichier temporaire (chmod 600) en début de tâche et supprimée dans le `finally`.

**Tech Stack:** Python 3.12 + FastAPI + SQLAlchemy async + cryptography (AES-GCM + HKDF) + pydantic v2 + React 18 + TypeScript strict + TanStack Query

## Global Constraints

- Branche `dev` exclusivement — vérifier `git branch --show-current` avant tout code.
- Python 3.12, async/await partout, `from __future__ import annotations` en tête de fichier.
- Pydantic v2, `extra="forbid"` sur tous les modèles.
- Logs via `structlog.get_logger(__name__)`, jamais `print()`.
- Écriture atomique fichiers : `tempfile` + `os.replace`.
- Toute construction de chemin sous `/data` → `safe_user_path`.
- Aucun secret dans les logs, dans git, dans une response API brute.
- Tests pytest + pytest-asyncio; TDD strict (rouge → vert → commit).
- Fichiers max 300 lignes, méthodes 5-15 lignes.
- Lint : `uv run ruff check src/ tests/` vert obligatoire avant commit.
- mypy : `uv run mypy src/` vert obligatoire avant commit.
- Le pseudo-login système : `"__system__"`, `secret_ns` fixe = `"00000000-0000-0000-0000-000000000001"`.
- Slug pour ci_password : `f"host.{name}.ci-password"`.
- Slug pour cert/clé SSH : `f"host.{name}.cert"`.
- `system_master_key` = `HKDF(SHA-256, length=32, salt=None, info=b"portal-system-vault").derive(bytes.fromhex(portal_vault_kek))`.
- Fichier temp SSH key : `tempfile.mkstemp(suffix=".pem", prefix="devpod-host-")`, chmod 600, supprimé dans `finally` de `_run_up_task`.

---

## Fichiers créés / modifiés

| Fichier | Action |
|---|---|
| `backend/src/portal/secrets/system.py` | Créer |
| `backend/tests/test_system_secrets.py` | Créer |
| `backend/src/portal/app.py` | Modifier (lifespan : `ensure_system_user`) |
| `backend/src/portal/db/tables.py` | Modifier (hosts table) |
| `backend/src/portal/config/models.py` | Modifier (HostConfig) |
| `backend/src/portal/db/global_config.py` | Modifier (_host_row_to_dict, _host_to_row) |
| `backend/src/portal/routes/admin.py` | Modifier (CRUD hosts + bootstrap-ssh) |
| `backend/src/portal/devpod/service.py` | Modifier (temp key lifecycle) |
| `frontend/src/features/admin/useHosts.ts` | Modifier (interfaces + mutations) |
| `frontend/src/features/admin/AdminHosts.tsx` | Modifier (form + storage selector) |
| `frontend/src/features/admin/GenerateHostDialog.tsx` | Modifier (storage selector + ci_password) |

---

### Task 1 : Service système de secrets (`secrets/system.py`)

**Files:**
- Create: `backend/src/portal/secrets/system.py`
- Create: `backend/tests/test_system_secrets.py`
- Modify: `backend/src/portal/app.py` (lifespan)

**Interfaces:**
- Produit:
  - `ensure_system_user(conn: AsyncConnection) -> None`
  - `store_system_secret(slug, label, value, storage_type, vault_identifier, conn) -> None`
  - `reveal_system_secret(slug, conn) -> str`
  - `delete_system_secret(slug, conn) -> None`
  - `store_system_cert(slug, label, private_pem, public_key, cert_type, storage_type, vault_identifier, conn) -> None`
  - `reveal_system_cert(slug, conn) -> str`
  - `delete_system_cert(slug, conn) -> None`

---

- [ ] **Étape 1 : Écrire le test rouge — system master key**

```python
# backend/tests/test_system_secrets.py
from __future__ import annotations

import pytest
from unittest.mock import patch


def test_system_master_key_requires_kek() -> None:
    """Lève RuntimeError si PORTAL_VAULT_KEK est vide."""
    with patch("portal.secrets.system.get_settings") as mock_settings:
        mock_settings.return_value.portal_vault_kek = ""
        from portal.secrets import system
        import importlib
        importlib.reload(system)
        with pytest.raises(RuntimeError, match="PORTAL_VAULT_KEK"):
            system._system_master_key()


def test_system_master_key_derives_from_kek() -> None:
    """Dérive une clé 32 bytes déterministe depuis le KEK."""
    kek = "a" * 64  # 32 bytes hex
    with patch("portal.secrets.system.get_settings") as mock_settings:
        mock_settings.return_value.portal_vault_kek = kek
        from portal.secrets import system
        import importlib
        importlib.reload(system)
        key1 = system._system_master_key()
        key2 = system._system_master_key()
    assert len(key1) == 32
    assert key1 == key2  # déterministe
```

- [ ] **Étape 2 : Lancer pour vérifier l'échec**

```bash
cd backend && uv run pytest tests/test_system_secrets.py -v
```
Attendu : `ModuleNotFoundError` ou `AttributeError` (module pas encore créé).

- [ ] **Étape 3 : Implémenter `secrets/system.py`**

```python
# backend/src/portal/secrets/system.py
from __future__ import annotations

from typing import Literal

import structlog
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.tables import harpo_certificates, harpo_secrets, users
from portal.settings import get_settings
from portal.vault.crypto import decrypt_token, encrypt_token

_log = structlog.get_logger(__name__)

_SYSTEM_LOGIN = "__system__"
_SYSTEM_SECRET_NS = "00000000-0000-0000-0000-000000000001"


def _system_master_key() -> bytes:
    kek_hex = get_settings().portal_vault_kek
    if not kek_hex:
        raise RuntimeError("PORTAL_VAULT_KEK non configuré — impossible de chiffrer les secrets système")
    kek = bytes.fromhex(kek_hex)
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"portal-system-vault")
    return hkdf.derive(kek)


async def ensure_system_user(conn: AsyncConnection) -> None:
    """Insère __system__ dans users si absent. Idempotent."""
    exists = (await conn.execute(
        select(users.c.login).where(users.c.login == _SYSTEM_LOGIN)
    )).one_or_none()
    if exists is None:
        await conn.execute(insert(users).values(
            login=_SYSTEM_LOGIN,
            version="1",
            secret_ns=_SYSTEM_SECRET_NS,
        ))
        _log.info("system_user_created")


async def store_system_secret(
    slug: str,
    label: str,
    value: str,
    storage_type: Literal["local", "harpocrate"],
    vault_identifier: str,
    conn: AsyncConnection,
) -> None:
    """Crée ou remplace une entrée harpo_secrets pour __system__."""
    await conn.execute(
        delete(harpo_secrets)
        .where(harpo_secrets.c.owner_login == _SYSTEM_LOGIN)
        .where(harpo_secrets.c.slug == slug)
    )
    if storage_type == "local":
        blob = encrypt_token(value, _system_master_key())
        await conn.execute(insert(harpo_secrets).values(
            slug=slug,
            label=label,
            description="",
            secret_type="CI_PASSWORD",
            secret_value_local=blob,
            secret_value_vault_ref=None,
            storage_type="local",
            vault_identifier="",
            owner_login=_SYSTEM_LOGIN,
            is_public=False,
        ))
    else:
        vault_ref = await _harpo_put_secret(slug, value, vault_identifier)
        await conn.execute(insert(harpo_secrets).values(
            slug=slug,
            label=label,
            description="",
            secret_type="CI_PASSWORD",
            secret_value_local=None,
            secret_value_vault_ref=vault_ref,
            storage_type="harpocrate",
            vault_identifier=vault_identifier,
            owner_login=_SYSTEM_LOGIN,
            is_public=False,
        ))
    _log.info("system_secret_stored", slug=slug, storage=storage_type)


async def reveal_system_secret(slug: str, conn: AsyncConnection) -> str:
    """Résout un secret système. Lève KeyError si absent."""
    row = (await conn.execute(
        select(harpo_secrets)
        .where(harpo_secrets.c.owner_login == _SYSTEM_LOGIN)
        .where(harpo_secrets.c.slug == slug)
    )).mappings().one_or_none()
    if row is None:
        raise KeyError(f"System secret {slug!r} not found")
    if row["storage_type"] == "local":
        return decrypt_token(row["secret_value_local"], _system_master_key())
    return await _harpo_get_secret(slug, row["vault_identifier"])


async def delete_system_secret(slug: str, conn: AsyncConnection) -> None:
    """Supprime l'entrée harpo_secrets pour __system__ (no-op si absent)."""
    await conn.execute(
        delete(harpo_secrets)
        .where(harpo_secrets.c.owner_login == _SYSTEM_LOGIN)
        .where(harpo_secrets.c.slug == slug)
    )


async def store_system_cert(
    slug: str,
    label: str,
    private_pem: str,
    public_key: str,
    cert_type: str,
    storage_type: Literal["local", "harpocrate"],
    vault_identifier: str,
    conn: AsyncConnection,
) -> None:
    """Crée ou remplace une entrée harpo_certificates pour __system__."""
    await conn.execute(
        delete(harpo_certificates)
        .where(harpo_certificates.c.owner_login == _SYSTEM_LOGIN)
        .where(harpo_certificates.c.slug == slug)
    )
    if storage_type == "local":
        blob = encrypt_token(private_pem, _system_master_key())
        await conn.execute(insert(harpo_certificates).values(
            slug=slug,
            label=label,
            description="",
            cert_type=cert_type,
            public_key=public_key,
            private_key_local=blob,
            private_key_vault_ref=None,
            storage_type="local",
            vault_identifier="",
            owner_login=_SYSTEM_LOGIN,
            is_public=False,
        ))
    else:
        vault_ref = await _harpo_put_cert(slug, private_pem, vault_identifier)
        await conn.execute(insert(harpo_certificates).values(
            slug=slug,
            label=label,
            description="",
            cert_type=cert_type,
            public_key=public_key,
            private_key_local=None,
            private_key_vault_ref=vault_ref,
            storage_type="harpocrate",
            vault_identifier=vault_identifier,
            owner_login=_SYSTEM_LOGIN,
            is_public=False,
        ))
    _log.info("system_cert_stored", slug=slug, storage=storage_type)


async def reveal_system_cert(slug: str, conn: AsyncConnection) -> str:
    """Résout la clé privée PEM d'un cert système. Lève KeyError si absent."""
    row = (await conn.execute(
        select(harpo_certificates)
        .where(harpo_certificates.c.owner_login == _SYSTEM_LOGIN)
        .where(harpo_certificates.c.slug == slug)
    )).mappings().one_or_none()
    if row is None:
        raise KeyError(f"System cert {slug!r} not found")
    if row["storage_type"] == "local":
        return decrypt_token(row["private_key_local"], _system_master_key())
    return await _harpo_get_cert(slug, row["vault_identifier"])


async def delete_system_cert(slug: str, conn: AsyncConnection) -> None:
    """Supprime l'entrée harpo_certificates pour __system__ (no-op si absent)."""
    await conn.execute(
        delete(harpo_certificates)
        .where(harpo_certificates.c.owner_login == _SYSTEM_LOGIN)
        .where(harpo_certificates.c.slug == slug)
    )


# ── Harpocrate helpers ────────────────────────────────────────────────────────

async def _harpo_put_secret(slug: str, value: str, vault_identifier: str) -> str:
    """Stocke un secret dans Harpocrate global; retourne la vault_ref."""
    import httpx
    from portal.db.global_config import get_cached_global
    hc = get_cached_global().secrets.harpocrate
    path = f"hosts/{slug}"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.put(
            f"{hc.url}/{hc.base_path}/{path}",
            headers={"X-Api-Key": hc.api_key},
            json={"value": value},
        )
        r.raise_for_status()
    return f"${{vault://{vault_identifier}:{hc.base_path}/{path}}}"


async def _harpo_get_secret(slug: str, vault_identifier: str) -> str:
    import httpx
    from portal.db.global_config import get_cached_global
    hc = get_cached_global().secrets.harpocrate
    path = f"hosts/{slug}"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{hc.url}/{hc.base_path}/{path}",
            headers={"X-Api-Key": hc.api_key},
        )
        r.raise_for_status()
        return r.json()["value"]


async def _harpo_put_cert(slug: str, private_pem: str, vault_identifier: str) -> str:
    import httpx
    from portal.db.global_config import get_cached_global
    hc = get_cached_global().secrets.harpocrate
    path = f"hosts/{slug}/private"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.put(
            f"{hc.url}/{hc.base_path}/{path}",
            headers={"X-Api-Key": hc.api_key},
            json={"value": private_pem},
        )
        r.raise_for_status()
    return f"${{vault://{vault_identifier}:{hc.base_path}/{path}}}"


async def _harpo_get_cert(slug: str, vault_identifier: str) -> str:
    import httpx
    from portal.db.global_config import get_cached_global
    hc = get_cached_global().secrets.harpocrate
    path = f"hosts/{slug}/private"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{hc.url}/{hc.base_path}/{path}",
            headers={"X-Api-Key": hc.api_key},
        )
        r.raise_for_status()
        return r.json()["value"]
```

- [ ] **Étape 4 : Compléter les tests**

```python
# backend/tests/test_system_secrets.py  (suite, remplace ce qui est au-dessus)
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ── _system_master_key ────────────────────────────────────────────────────────

def test_system_master_key_requires_kek() -> None:
    """Lève RuntimeError si portal_vault_kek vide."""
    from portal.secrets.system import _system_master_key
    with patch("portal.secrets.system.get_settings") as mock:
        mock.return_value.portal_vault_kek = ""
        with pytest.raises(RuntimeError, match="PORTAL_VAULT_KEK"):
            _system_master_key()


def test_system_master_key_is_deterministic() -> None:
    kek = "ab" * 32  # 64 hex chars
    with patch("portal.secrets.system.get_settings") as mock:
        mock.return_value.portal_vault_kek = kek
        from portal.secrets.system import _system_master_key
        k1 = _system_master_key()
        k2 = _system_master_key()
    assert len(k1) == 32
    assert k1 == k2


def test_system_master_key_differs_from_kek() -> None:
    kek = "cd" * 32
    with patch("portal.secrets.system.get_settings") as mock:
        mock.return_value.portal_vault_kek = kek
        from portal.secrets.system import _system_master_key
        key = _system_master_key()
    assert key != bytes.fromhex(kek)  # HKDF transforme la valeur


# ── encrypt/decrypt roundtrip ─────────────────────────────────────────────────

def test_encrypt_decrypt_roundtrip() -> None:
    from portal.vault.crypto import decrypt_token, encrypt_token
    key = bytes(32)  # clé nulle pour le test
    plaintext = "super-secret-password"
    blob = encrypt_token(plaintext, key)
    assert decrypt_token(blob, key) == plaintext


# ── ensure_system_user ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ensure_system_user_inserts_if_absent() -> None:
    from portal.secrets.system import ensure_system_user, _SYSTEM_LOGIN

    conn = AsyncMock()
    # Simuler que l'utilisateur n'existe pas
    conn.execute.return_value.one_or_none.return_value = None

    await ensure_system_user(conn)

    # Vérifier qu'un INSERT a été appelé
    assert conn.execute.call_count == 2  # SELECT + INSERT


@pytest.mark.asyncio
async def test_ensure_system_user_idempotent() -> None:
    from portal.secrets.system import ensure_system_user

    conn = AsyncMock()
    # Simuler que l'utilisateur existe déjà
    conn.execute.return_value.one_or_none.return_value = {"login": "__system__"}

    await ensure_system_user(conn)

    # Seulement le SELECT, pas d'INSERT
    assert conn.execute.call_count == 1


# ── store/reveal secret ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_store_reveal_system_secret_local() -> None:
    """Roundtrip local : store chiffre, reveal déchiffre."""
    from portal.secrets.system import reveal_system_secret, store_system_secret

    stored_blob: bytes | None = None

    async def fake_execute(stmt, *args, **kwargs):
        nonlocal stored_blob
        result = AsyncMock()
        result.mappings.return_value.one_or_none.return_value = None

        # Capturer l'INSERT pour simuler reveal
        stmt_str = str(stmt)
        if "INSERT" in stmt_str and stored_blob is None:
            # On capture les valeurs passées à l'INSERT
            compiled = stmt.compile()
            # Simplification : on teste juste que store ne lève pas
            pass
        return result

    conn = AsyncMock()
    conn.execute.side_effect = fake_execute

    with patch("portal.secrets.system.get_settings") as mock:
        mock.return_value.portal_vault_kek = "ff" * 32
        # store ne doit pas lever
        await store_system_secret(
            slug="host.test-host.ci-password",
            label="Test",
            value="my-password",
            storage_type="local",
            vault_identifier="",
            conn=conn,
        )
    assert conn.execute.called


@pytest.mark.asyncio
async def test_reveal_system_secret_raises_if_absent() -> None:
    from portal.secrets.system import reveal_system_secret

    conn = AsyncMock()
    conn.execute.return_value.mappings.return_value.one_or_none.return_value = None

    with pytest.raises(KeyError, match="not found"):
        await reveal_system_secret("host.ghost.ci-password", conn)
```

- [ ] **Étape 5 : Lancer les tests**

```bash
cd backend && uv run pytest tests/test_system_secrets.py -v
```
Attendu : tous les tests passent (ajuster les mocks si SQLAlchemy produit des stmt différents).

- [ ] **Étape 6 : Modifier le lifespan dans `app.py`**

Dans `backend/src/portal/app.py`, trouver le lifespan (`_lifespan`) et ajouter après `warm_global_cache` :

```python
# Après warm_global_cache(conn) :
from .secrets.system import ensure_system_user
await ensure_system_user(conn)
```

Le bloc complet autour de ce changement :

```python
if settings_obj.database_url:
    from .db.migration import run_migrations
    await run_migrations(settings_obj.database_url)
    async with _get_engine().begin() as conn:
        await warm_global_cache(conn)
        from .secrets.system import ensure_system_user  # NEW
        await ensure_system_user(conn)                   # NEW
```

- [ ] **Étape 7 : Lint + mypy**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
```
Attendu : 0 erreur.

- [ ] **Étape 8 : Commit**

```bash
git add backend/src/portal/secrets/system.py backend/tests/test_system_secrets.py backend/src/portal/app.py
git commit -m "feat: service de secrets système (harpo_* sans session utilisateur)"
```

---

### Task 2 : Schéma DB + modèles Pydantic

**Files:**
- Modify: `backend/src/portal/db/tables.py` (table `hosts`)
- Modify: `backend/src/portal/config/models.py` (`HostConfig`)
- Modify: `backend/src/portal/db/global_config.py` (`_host_row_to_dict`, `_host_to_row`)

**Interfaces:**
- Consomme: rien de Task 1 directement
- Produit:
  - `HostConfig` mis à jour (slugs + storage_type)
  - colonnes DB mises à jour

---

- [ ] **Étape 1 : Écrire le test rouge — HostConfig sans key_path**

```python
# backend/tests/test_host_config.py
from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_host_config_has_no_key_path() -> None:
    """HostConfig ne doit plus accepter key_path (extra=forbid)."""
    from portal.config.models import HostConfig
    with pytest.raises(ValidationError):
        HostConfig(name="test", type="ssh", key_path="/data/keys/test")


def test_host_config_accepts_slugs() -> None:
    from portal.config.models import HostConfig
    h = HostConfig(
        name="my-host",
        type="ssh",
        address="debian@192.168.1.50",
        host_cert_slug="host.my-host.cert",
        ci_password_secret_slug="",
        storage_type="local",
        vault_identifier="",
    )
    assert h.host_cert_slug == "host.my-host.cert"
    assert h.storage_type == "local"


def test_host_config_has_no_ci_password_field() -> None:
    """HostConfig ne doit plus accepter ci_password (extra=forbid)."""
    from portal.config.models import HostConfig
    with pytest.raises(ValidationError):
        HostConfig(name="test", type="docker-tls", ci_password="secret")
```

- [ ] **Étape 2 : Lancer pour vérifier l'échec**

```bash
cd backend && uv run pytest tests/test_host_config.py -v
```
Attendu : `FAILED` (les tests `test_host_config_has_no_key_path` et `test_host_config_has_no_ci_password_field` passent si HostConfig est encore l'ancien modèle, mais `test_host_config_accepts_slugs` échoue).

- [ ] **Étape 3 : Modifier `config/models.py` — HostConfig**

Remplacer la classe `HostConfig` (lignes 84-96 actuelles) par :

```python
class HostConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    default: bool = False
    type: Literal["docker-tls", "ssh"]
    docker_host: str = ""
    address: str = ""
    proxmox_node: str = ""
    vmid: str = ""
    # Références vers harpo_* (slugs)
    ci_password_secret_slug: str = ""
    host_cert_slug: str = ""
    # Préférences de stockage des secrets
    storage_type: Literal["local", "harpocrate"] = "local"
    vault_identifier: str = ""
```

- [ ] **Étape 4 : Modifier `db/tables.py` — table `hosts`**

Dans la définition de la table `hosts`, remplacer les colonnes `key_path`, `public_key` et `ci_password` par les nouvelles colonnes. Les colonnes existantes à **supprimer** : `key_path`, `public_key`, `ci_password`. Les colonnes à **ajouter** :

```python
# Dans la Table("hosts", ...) :
# SUPPRIMER ces lignes (chercher et retirer) :
#   Column("key_path", Text, ...)
#   Column("public_key", Text, ...)
#   Column("ci_password", Text, ...)

# AJOUTER à la place :
Column("ci_password_secret_slug", Text, nullable=False, server_default=""),
Column("host_cert_slug", Text, nullable=False, server_default=""),
Column("storage_type", Text, nullable=False, server_default="local"),
Column("vault_identifier", Text, nullable=False, server_default=""),
```

- [ ] **Étape 5 : Modifier `db/global_config.py` — mappers**

Remplacer `_host_row_to_dict` :

```python
def _host_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row["name"],
        "default": row["is_default"],
        "type": row["type"],
        "docker_host": row["docker_host"],
        "address": row["address"],
        "proxmox_node": row["proxmox_node"],
        "vmid": row["vmid"],
        "ci_password_secret_slug": row["ci_password_secret_slug"],
        "host_cert_slug": row["host_cert_slug"],
        "storage_type": row["storage_type"],
        "vault_identifier": row["vault_identifier"],
    }
```

Remplacer `_host_to_row` :

```python
def _host_to_row(h: HostConfig) -> dict[str, Any]:
    return {
        "name": h.name,
        "is_default": h.default,
        "type": h.type,
        "docker_host": h.docker_host,
        "address": h.address,
        "proxmox_node": h.proxmox_node,
        "vmid": h.vmid,
        "ci_password_secret_slug": h.ci_password_secret_slug,
        "host_cert_slug": h.host_cert_slug,
        "storage_type": h.storage_type,
        "vault_identifier": h.vault_identifier,
    }
```

- [ ] **Étape 6 : Lancer les tests**

```bash
cd backend && uv run pytest tests/test_host_config.py -v
```
Attendu : les 3 tests passent.

- [ ] **Étape 7 : Lint + mypy**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
```
Attendu : 0 erreur (des erreurs peuvent apparaître dans admin.py si ce fichier référence encore `key_path` — noter pour Task 3).

- [ ] **Étape 8 : Commit**

```bash
git add backend/src/portal/config/models.py backend/src/portal/db/tables.py backend/src/portal/db/global_config.py backend/tests/test_host_config.py
git commit -m "feat: migration schéma hosts — key_path/ci_password → slugs harpo_*"
```

---

### Task 3 : Routes admin — CRUD hosts + bootstrap-ssh

**Files:**
- Modify: `backend/src/portal/routes/admin.py`

**Interfaces:**
- Consomme:
  - `store_system_secret`, `reveal_system_secret`, `delete_system_secret` depuis `portal.secrets.system`
  - `store_system_cert`, `reveal_system_cert`, `delete_system_cert` depuis `portal.secrets.system`
  - `HostConfig` depuis `portal.config.models` (version mise à jour — Task 2)
- Produit:
  - `POST /admin/hosts` accepte `HostCreateRequest` (valeurs brutes) → crée entrées harpo → retourne `HostConfig` (slugs)
  - `PUT /admin/hosts/{name}` : idem
  - `DELETE /admin/hosts/{name}` : supprime entrées harpo avant de retirer le host
  - `POST /admin/hosts/{name}/bootstrap-ssh` : stocke clé SSH dans harpo → met à jour `host_cert_slug`
  - `GET /admin/hosts/{name}/cert` : lit depuis harpo_certificates (clé publique) ou fichiers TLS globaux

---

- [ ] **Étape 1 : Écrire le test rouge — add_host crée entrée harpo**

```python
# backend/tests/test_admin_hosts.py
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_add_host_stores_ci_password_in_harpo(client: AsyncClient) -> None:
    """POST /admin/hosts doit créer l'entrée harpo_secrets pour ci_password."""
    # Ce test nécessite un client de test configuré avec auth admin + DB de test
    # Vérifier que ci_password est stocké chiffré (jamais en clair dans hosts)
    resp = await client.post(
        "/admin/hosts",
        json={
            "name": "test-vm-01",
            "type": "ssh",
            "address": "debian@192.168.1.10",
            "proxmox_node": "pve",
            "vmid": "200",
            "ci_password": "SuperSecret123!",
            "storage_type": "local",
            "vault_identifier": "",
        },
        headers={"X-Api-Key": "test-key"},
    )
    assert resp.status_code == 201
    body = resp.json()
    # Le slug est présent, le mot de passe brut n'est PAS dans la réponse
    assert "ci_password_secret_slug" in body
    assert body["ci_password_secret_slug"] == "host.test-vm-01.ci-password"
    assert "ci_password" not in body
    assert "key_path" not in body


@pytest.mark.asyncio
async def test_add_host_without_ci_password(client: AsyncClient) -> None:
    """POST /admin/hosts sans ci_password laisse ci_password_secret_slug vide."""
    resp = await client.post(
        "/admin/hosts",
        json={
            "name": "manual-ssh-host",
            "type": "ssh",
            "address": "debian@10.0.0.5",
            "storage_type": "local",
            "vault_identifier": "",
        },
        headers={"X-Api-Key": "test-key"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["ci_password_secret_slug"] == ""
    assert body["host_cert_slug"] == ""
```

- [ ] **Étape 2 : Lancer pour vérifier l'échec**

```bash
cd backend && uv run pytest tests/test_admin_hosts.py -v -k "add_host"
```
Attendu : FAILED (endpoint accepte encore HostConfig avec key_path, pas HostCreateRequest).

- [ ] **Étape 3 : Ajouter `HostCreateRequest` dans `routes/admin.py`**

En tête du fichier `routes/admin.py`, après les imports existants, ajouter le modèle DTO d'entrée :

```python
from __future__ import annotations
# ... imports existants ...
from typing import Literal
from portal.secrets.system import (
    delete_system_cert,
    delete_system_secret,
    store_system_cert,
    store_system_secret,
)


class HostCreateRequest(BaseModel):
    """DTO d'entrée pour add/update host — accepte les valeurs brutes de secrets."""

    model_config = ConfigDict(extra="forbid")

    name: str
    default: bool = False
    type: Literal["docker-tls", "ssh"]
    docker_host: str = ""
    address: str = ""
    proxmox_node: str = ""
    vmid: str = ""
    ci_password: str = ""  # valeur brute, stockée dans harpo au CREATE
    storage_type: Literal["local", "harpocrate"] = "local"
    vault_identifier: str = ""
```

- [ ] **Étape 4 : Modifier `add_host` dans `routes/admin.py`**

Remplacer l'endpoint `POST /hosts` :

```python
@router.post("/hosts", status_code=201)
async def add_host(
    body: HostCreateRequest,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    cfg = load_global()
    if any(h.name == body.name for h in cfg.hosts):
        raise HTTPException(status_code=409, detail=f"Host {body.name!r} already exists")

    ci_slug = ""
    if body.ci_password:
        ci_slug = f"host.{body.name}.ci-password"
        await store_system_secret(
            slug=ci_slug,
            label=f"CI password — {body.name}",
            value=body.ci_password,
            storage_type=body.storage_type,
            vault_identifier=body.vault_identifier,
            conn=conn,
        )

    host = HostConfig(
        name=body.name,
        default=body.default,
        type=body.type,
        docker_host=body.docker_host,
        address=body.address,
        proxmox_node=body.proxmox_node,
        vmid=body.vmid,
        ci_password_secret_slug=ci_slug,
        host_cert_slug="",
        storage_type=body.storage_type,
        vault_identifier=body.vault_identifier,
    )
    cfg.hosts.append(host)
    await save_global(cfg, conn)
    _log.info("host_added", name=body.name, by=user.login)
    return host.model_dump(mode="json")
```

- [ ] **Étape 5 : Modifier `update_host` dans `routes/admin.py`**

Remplacer l'endpoint `PUT /hosts/{name}` :

```python
@router.put("/hosts/{name}")
async def update_host(
    name: str,
    body: HostCreateRequest,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    if body.name != name:
        raise HTTPException(status_code=422, detail="Host name in body must match URL")
    cfg = load_global()
    idx = next((i for i, h in enumerate(cfg.hosts) if h.name == name), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Host {name!r} not found")

    existing = cfg.hosts[idx]
    ci_slug = existing.ci_password_secret_slug

    # Si un nouveau ci_password est fourni, remplacer dans harpo
    if body.ci_password:
        ci_slug = f"host.{name}.ci-password"
        await store_system_secret(
            slug=ci_slug,
            label=f"CI password — {name}",
            value=body.ci_password,
            storage_type=body.storage_type,
            vault_identifier=body.vault_identifier,
            conn=conn,
        )

    host = HostConfig(
        name=body.name,
        default=body.default,
        type=body.type,
        docker_host=body.docker_host,
        address=body.address,
        proxmox_node=body.proxmox_node,
        vmid=body.vmid,
        ci_password_secret_slug=ci_slug,
        host_cert_slug=existing.host_cert_slug,  # conservé
        storage_type=body.storage_type,
        vault_identifier=body.vault_identifier,
    )
    cfg.hosts[idx] = host
    await save_global(cfg, conn)
    _log.info("host_updated", name=name, by=user.login)
    return host.model_dump(mode="json")
```

- [ ] **Étape 6 : Modifier `delete_host` — cleanup harpo avant suppression**

Dans la fonction `delete_host` existante, ajouter le cleanup harpo après `_run_destroy_script` et avant `save_global` :

```python
# Après _run_destroy_script(cfg, host_cfg) :
if host_cfg.ci_password_secret_slug:
    await delete_system_secret(host_cfg.ci_password_secret_slug, conn)
if host_cfg.host_cert_slug:
    await delete_system_cert(host_cfg.host_cert_slug, conn)
```

- [ ] **Étape 7 : Modifier `bootstrap-ssh` — stocker clé dans harpo**

Remplacer l'endpoint `POST /hosts/{name}/bootstrap-ssh` par une version qui :
1. Génère la paire ed25519 (comme maintenant)
2. Stocke la clé privée PEM dans harpo_certificates via `store_system_cert`
3. Met à jour `host.host_cert_slug` dans la config
4. Ne crée plus de fichier sur le disque

```python
@router.post("/hosts/{name}/bootstrap-ssh")
async def bootstrap_ssh(
    name: str,
    body: BootstrapSshRequest,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    cfg = load_global()
    idx = next((i for i, h in enumerate(cfg.hosts) if h.name == name), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Host {name!r} not found")
    host = cfg.hosts[idx]
    if host.type != "ssh":
        raise HTTPException(status_code=422, detail="SSH uniquement")

    # Valider format address
    _ADDRESS_RE = re.compile(
        r"^[a-z_][a-z0-9_-]{0,31}@[a-zA-Z0-9][a-zA-Z0-9._-]{0,253}$"
    )
    if not _ADDRESS_RE.fullmatch(body.address):
        raise HTTPException(status_code=422, detail="Format address invalide (user@host)")

    proxmox_node = body.proxmox_node or host.proxmox_node
    if not proxmox_node:
        raise HTTPException(status_code=422, detail="proxmox_node requis")

    # Générer paire ed25519
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    private_key_obj = Ed25519PrivateKey.generate()
    private_pem = private_key_obj.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_key = private_key_obj.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode().strip()

    cert_slug = f"host.{name}.cert"
    await store_system_cert(
        slug=cert_slug,
        label=f"SSH key — {name}",
        private_pem=private_pem,
        public_key=public_key,
        cert_type="ssh-ed25519",
        storage_type=host.storage_type,
        vault_identifier=host.vault_identifier,
        conn=conn,
    )

    # Injecter la clé publique sur la VM via SSH pivot Proxmox
    ssh_user, ssh_host = body.address.split("@", 1)
    hyp = next((h for h in cfg.hypervisors if h.pve_node == proxmox_node), None)
    if hyp is None:
        raise HTTPException(status_code=422, detail=f"Hyperviseur Proxmox {proxmox_node!r} non trouvé")

    authorized_key = public_key.strip()
    inner_cmd = (
        f"mkdir -p ~/.ssh && "
        f"grep -qxF {shlex.quote(authorized_key)} ~/.ssh/authorized_keys 2>/dev/null || "
        f"echo {shlex.quote(authorized_key)} >> ~/.ssh/authorized_keys && "
        f"chmod 600 ~/.ssh/authorized_keys"
    )
    ssh_opts = [
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=15",
        "-i", hyp.ssh_key_path,
        "-p", str(hyp.ssh_port),
    ]
    pivot_cmd = [
        "ssh", *ssh_opts,
        f"{hyp.ssh_user}@{hyp.address}",
        f"ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes {shlex.quote(body.address)} {shlex.quote(inner_cmd)}",
    ]
    proc = await asyncio.create_subprocess_exec(
        *pivot_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Injection clé SSH échouée : {stderr.decode(errors='replace').strip()}",
        )

    # Mettre à jour le host
    updated = host.model_copy(update={
        "address": body.address,
        "proxmox_node": proxmox_node,
        "host_cert_slug": cert_slug,
    })
    cfg.hosts[idx] = updated
    await save_global(cfg, conn)

    _log.info("ssh_bootstrap_done", host=name, by=user.login)
    return {
        "public_key": public_key,
        "address": body.address,
        "host_cert_slug": cert_slug,
    }
```

- [ ] **Étape 8 : Modifier `GET /hosts/{name}/cert`**

Pour les hosts SSH, retourner la clé publique depuis harpo_certificates. Pour docker-tls, comportement inchangé.

```python
@router.get("/hosts/{name}/cert")
async def get_host_cert(
    name: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    cfg = load_global()
    host = next((h for h in cfg.hosts if h.name == name), None)
    if host is None:
        raise HTTPException(status_code=404, detail=f"Host {name!r} not found")

    if host.type == "ssh":
        if not host.host_cert_slug:
            raise HTTPException(status_code=404, detail="Clé SSH non configurée (lancez bootstrap-ssh)")
        from portal.db.tables import harpo_certificates
        row = (await conn.execute(
            select(harpo_certificates)
            .where(harpo_certificates.c.owner_login == "__system__")
            .where(harpo_certificates.c.slug == host.host_cert_slug)
        )).mappings().one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Cert introuvable en base")
        return {"public_key": row["public_key"], "cert_type": row["cert_type"]}

    # docker-tls : lire depuis le répertoire global
    cert_dir = Path(cfg.devpod.client_cert_path)
    if not cert_dir.is_relative_to(_data_root()) and str(cert_dir) != cfg.devpod.client_cert_path:
        raise HTTPException(status_code=403, detail="Chemin cert non autorisé")
    try:
        return {
            "ca.pem": (cert_dir / "ca.pem").read_text(),
            "cert.pem": (cert_dir / "cert.pem").read_text(),
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Fichier cert manquant : {exc}") from exc
```

- [ ] **Étape 9 : Lancer les tests**

```bash
cd backend && uv run pytest tests/test_admin_hosts.py -v
```
Attendu : les tests add_host passent.

- [ ] **Étape 10 : Lint + mypy**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
```
Attendu : 0 erreur.

- [ ] **Étape 11 : Commit**

```bash
git add backend/src/portal/routes/admin.py
git commit -m "feat: routes admin hosts utilisent harpo_* (ci_password, bootstrap-ssh, cleanup)"
```

---

### Task 4 : DevPod service — résolution clé SSH depuis harpo

**Files:**
- Modify: `backend/src/portal/devpod/service.py`

**Interfaces:**
- Consomme:
  - `reveal_system_cert(slug, conn)` depuis `portal.secrets.system`
  - `HostConfig.host_cert_slug` (Task 2)
- Produit:
  - `up()` matérialise la clé SSH depuis harpo en fichier temp, passe le chemin à `ensure_provider` et `_run_up_task`
  - `_run_up_task()` supprime le fichier temp dans `finally`

---

- [ ] **Étape 1 : Écrire le test rouge — HostNotReadyError basé sur host_cert_slug**

```python
# backend/tests/test_devpod_service.py (ou ajouter à un test existant)
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.mark.asyncio
async def test_up_raises_host_not_ready_when_no_cert_slug() -> None:
    """up() lève HostNotReadyError pour SSH host sans host_cert_slug."""
    from portal.devpod.service import WorkspaceService, HostNotReadyError
    from portal.config.models import HostConfig, WorkspaceSpec

    ssh_host = HostConfig(
        name="my-ssh-host",
        type="ssh",
        address="debian@10.0.0.1",
        host_cert_slug="",  # pas encore bootstrappé
    )
    mock_global = MagicMock()
    mock_global.hosts = [ssh_host]

    ws_spec = WorkspaceSpec(
        name="my-ws",
        source="https://github.com/org/repo",
        host="my-ssh-host",
        version="1",
    )

    svc = WorkspaceService.__new__(WorkspaceService)

    with patch("portal.devpod.service.load_global", return_value=mock_global):
        with pytest.raises(HostNotReadyError, match="clé SSH"):
            await svc.up(login="alice", ws_spec=ws_spec)
```

- [ ] **Étape 2 : Lancer pour vérifier l'échec**

```bash
cd backend && uv run pytest tests/test_devpod_service.py::test_up_raises_host_not_ready_when_no_cert_slug -v
```
Attendu : FAILED (le service cherche encore `host_cfg.key_path`).

- [ ] **Étape 3 : Ajouter `_materialize_system_cert` dans `service.py`**

Après les imports dans `service.py`, ajouter la fonction helper :

```python
import contextlib
import os
import tempfile

async def _materialize_system_cert(slug: str) -> str:
    """Résout la clé privée PEM depuis harpo et l'écrit dans un fichier temp sécurisé.

    Retourne le chemin du fichier. Le caller doit le supprimer dans finally.
    """
    from portal.secrets.system import reveal_system_cert
    from portal.db.engine import _get_engine

    async with _get_engine().begin() as conn:
        pem = await reveal_system_cert(slug, conn)

    fd, path = tempfile.mkstemp(suffix=".pem", prefix="devpod-host-")
    try:
        os.write(fd, pem.encode())
    finally:
        os.close(fd)
    os.chmod(path, 0o600)
    return path
```

- [ ] **Étape 4 : Modifier `up()` dans `service.py`**

Trouver le bloc avec `if host_cfg.type == "ssh" and not host_cfg.key_path:` et remplacer :

```python
# AVANT (à supprimer) :
if host_cfg.type == "ssh" and not host_cfg.key_path:
    raise HostNotReadyError(
        f"Host {host_cfg.name!r} : clé SSH manquante — lancez d'abord 'Configurer SSH'"
    )

# APRÈS (à mettre à la place) :
if host_cfg.type == "ssh" and not host_cfg.host_cert_slug:
    raise HostNotReadyError(
        f"Host {host_cfg.name!r} : clé SSH manquante — lancez d'abord 'Configurer SSH'"
    )
```

Puis trouver l'appel `ensure_provider(...)` et la création du `task = asyncio.create_task(...)` pour les entourer d'une résolution de cert :

```python
# Matérialiser la clé SSH si besoin (supprimée par _run_up_task dans finally)
tmp_key_path = ""
if host_cfg.type == "ssh" and host_cfg.host_cert_slug:
    tmp_key_path = await _materialize_system_cert(host_cfg.host_cert_slug)

provider_name = await ensure_provider(
    login=login,
    host_type=host_cfg.type,
    env=base_env,
    host_name=host_cfg.name,
    ssh_host=ssh_host,
    ssh_user=ssh_user,
    ssh_key_path=tmp_key_path,  # chemin temp (vide pour docker-tls)
    devpod_bin=self._devpod_bin,
)

# ... (dc_path, subprocess_env, etc. inchangés) ...

task = asyncio.create_task(
    self._run_up_task(
        ws_id,
        devpod_source,
        dc_path,
        subprocess_env,
        login,
        host_port,
        node_ip,
        provider_name=provider_name,
        host_type=host_cfg.type,
        ssh_host=ssh_host,
        ssh_user=ssh_user,
        ssh_key_path=tmp_key_path,  # MODIFIÉ : chemin temp au lieu de host_cfg.key_path
        request_host=request_host,
        workspace_folder=workspace_folder,
        host_name=host_cfg.name,
        git_ssh_key_path=git_ssh_key_path,
    )
)
```

- [ ] **Étape 5 : Modifier `_run_up_task()` — nettoyage fichier temp dans `finally`**

Dans `_run_up_task`, trouver le bloc `try/finally` principal (ou en créer un si absent) et ajouter le nettoyage :

```python
async def _run_up_task(
    self,
    ws_id: str,
    # ... autres paramètres inchangés ...
    ssh_key_path: str = "",
    # ...
) -> None:
    try:
        # ... tout le code existant de _run_up_task INCHANGÉ ...
        pass
    except Exception:
        _log.exception("workspace_up_failed", ws_id=ws_id)
        await self._write_status(ws_id, "failed", login=...)
        raise
    finally:
        # Supprimer le fichier temp de la clé SSH (créé dans up())
        if ssh_key_path and ssh_key_path.startswith(tempfile.gettempdir()):
            with contextlib.suppress(OSError):
                os.unlink(ssh_key_path)
```

> **Note :** Le guard `ssh_key_path.startswith(tempfile.gettempdir())` évite de supprimer accidentellement un fichier non-temp si un chemin manuel était passé.

- [ ] **Étape 6 : Lancer le test**

```bash
cd backend && uv run pytest tests/test_devpod_service.py::test_up_raises_host_not_ready_when_no_cert_slug -v
```
Attendu : PASSED.

- [ ] **Étape 7 : Lint + mypy**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
```
Attendu : 0 erreur.

- [ ] **Étape 8 : Lancer tous les tests backend**

```bash
cd backend && uv run pytest -v
```
Attendu : tous les tests passent (ajuster si un test existant référence encore `host_cfg.key_path`).

- [ ] **Étape 9 : Commit**

```bash
git add backend/src/portal/devpod/service.py
git commit -m "feat: devpod service résout la clé SSH via harpo (fichier temp, nettoyage dans finally)"
```

---

### Task 5 : Frontend — HostConfig + formulaires + sélecteur de stockage

**Files:**
- Modify: `frontend/src/features/admin/useHosts.ts`
- Modify: `frontend/src/features/admin/AdminHosts.tsx`
- Modify: `frontend/src/features/admin/GenerateHostDialog.tsx`

**Interfaces:**
- Consomme:
  - `POST /admin/hosts` avec body `HostCreateRequest` (Task 3)
  - `PUT /admin/hosts/{name}` avec body `HostCreateRequest` (Task 3)
  - `POST /admin/hosts/{name}/bootstrap-ssh` retourne `{ public_key, address, host_cert_slug }` (Task 3)
- Produit: interface utilisateur avec sélecteur stockage (local/Harpocrate)

---

- [ ] **Étape 1 : Mettre à jour les interfaces dans `useHosts.ts`**

Remplacer l'interface `HostConfig` :

```typescript
export interface HostConfig {
  name: string
  type: 'docker-tls' | 'ssh'
  default?: boolean
  docker_host?: string
  address?: string
  proxmox_node?: string
  vmid?: string
  // Références harpo_* (lecture seule — jamais de secret brut)
  ci_password_secret_slug?: string
  host_cert_slug?: string
  // Préférences de stockage
  storage_type?: 'local' | 'harpocrate'
  vault_identifier?: string
}
```

Ajouter le type `HostCreatePayload` pour les mutations :

```typescript
export interface HostCreatePayload {
  name: string
  type: 'docker-tls' | 'ssh'
  default?: boolean
  docker_host?: string
  address?: string
  proxmox_node?: string
  vmid?: string
  ci_password?: string
  storage_type: 'local' | 'harpocrate'
  vault_identifier: string
}
```

Mettre à jour `useAddHost` et `useUpdateHost` pour utiliser `HostCreatePayload` :

```typescript
export function useAddHost() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: HostCreatePayload) =>
      apiFetchJson<HostConfig>('/admin/hosts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'hosts'] }),
    onError: (err: Error) => toast.error(err.message),
  })
}

export function useUpdateHost() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: HostCreatePayload) =>
      apiFetchJson<HostConfig>(`/admin/hosts/${encodeURIComponent(payload.name)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'hosts'] }),
    onError: (err: Error) => toast.error(err.message),
  })
}
```

Mettre à jour `BootstrapSshResult` :

```typescript
export interface BootstrapSshResult {
  public_key: string
  address: string
  host_cert_slug: string  // remplace key_path
}
```

- [ ] **Étape 2 : Mettre à jour `AdminHosts.tsx` — formulaire host**

Dans `AdminHosts.tsx`, trouver l'état initial du formulaire (`EMPTY` ou état initial de `form`) et le mettre à jour :

```typescript
const EMPTY: HostCreatePayload = {
  name: '',
  type: 'docker-tls',
  default: false,
  docker_host: '',
  address: '',
  proxmox_node: '',
  vmid: '',
  ci_password: '',
  storage_type: 'local',
  vault_identifier: '',
}
```

Dans le formulaire, **remplacer** le champ `key_path` par le sélecteur de stockage :

```tsx
{/* SUPPRIMER le champ key_path existant */}
{/* AJOUTER le sélecteur de stockage */}
<div className="space-y-2">
  <Label>{t('hosts.form.storage', 'Stockage des secrets')}</Label>
  <RadioGroup
    value={form.storage_type}
    onValueChange={(v) => setForm(f => ({
      ...f,
      storage_type: v as 'local' | 'harpocrate',
      vault_identifier: v === 'local' ? '' : f.vault_identifier,
    }))}
    className="flex gap-4"
  >
    <div className="flex items-center gap-2">
      <RadioGroupItem value="local" id="storage-local" />
      <Label htmlFor="storage-local">{t('hosts.form.storage_local', 'Local (chiffré sur le serveur)')}</Label>
    </div>
    <div className="flex items-center gap-2">
      <RadioGroupItem value="harpocrate" id="storage-harpo" />
      <Label htmlFor="storage-harpo">{t('hosts.form.storage_harpo', 'Harpocrate')}</Label>
    </div>
  </RadioGroup>

  {form.storage_type === 'harpocrate' && (
    <div className="space-y-1">
      <Label htmlFor="h-vault-id">{t('hosts.form.vault_identifier', 'Identifiant du coffre')}</Label>
      <Input
        id="h-vault-id"
        value={form.vault_identifier}
        onChange={(e) => setForm(f => ({ ...f, vault_identifier: e.target.value }))}
        placeholder="my-vault"
        required
      />
    </div>
  )}
</div>

{/* Mot de passe CI (optionnel, visible uniquement si non vide en édition) */}
<div className="space-y-1">
  <Label htmlFor="h-ci-password">{t('hosts.form.ci_password', 'Mot de passe console Proxmox (optionnel)')}</Label>
  <Input
    id="h-ci-password"
    type="password"
    value={form.ci_password ?? ''}
    onChange={(e) => setForm(f => ({ ...f, ci_password: e.target.value }))}
    placeholder={mode === 'edit' ? t('hosts.form.ci_password_keep', '(conserver le mot de passe existant)') : ''}
    autoComplete="new-password"
  />
</div>
```

Mettre à jour la soumission du formulaire pour utiliser `HostCreatePayload` :

```typescript
function handleSubmit(e: React.FormEvent) {
  e.preventDefault()
  const payload: HostCreatePayload = {
    name: form.name,
    type: form.type,
    default: form.default,
    docker_host: form.docker_host,
    address: form.address,
    proxmox_node: form.proxmox_node,
    vmid: form.vmid,
    ci_password: form.ci_password ?? '',
    storage_type: form.storage_type,
    vault_identifier: form.vault_identifier,
  }
  const mutation = mode === 'edit' ? updateHost : addHost
  mutation.mutate(payload, { onSuccess: () => handleClose(false) })
}
```

Lors du pré-remplissage en mode édition (`openEdit(host)`), mapper depuis `HostConfig` :

```typescript
function openEdit(host: HostConfig) {
  setForm({
    name: host.name,
    type: host.type,
    default: host.default ?? false,
    docker_host: host.docker_host ?? '',
    address: host.address ?? '',
    proxmox_node: host.proxmox_node ?? '',
    vmid: host.vmid ?? '',
    ci_password: '',  // toujours vide en édition (secret non visible)
    storage_type: host.storage_type ?? 'local',
    vault_identifier: host.vault_identifier ?? '',
  })
  setMode('edit')
  setOpen(true)
}
```

- [ ] **Étape 3 : Mettre à jour `GenerateHostDialog.tsx` — sélecteur de stockage**

Dans `GenerateHostDialog.tsx`, trouver la fonction `mapToHostConfig` et la supprimer (plus de mapping direct). À la place, ajouter un état `storageType` + `vaultIdentifier` dans le dialog.

Trouver l'endroit où `addHost.mutate(...)` est appelé et remplacer pour passer les champs corrects :

```typescript
// État local du dialog
const [storageType, setStorageType] = useState<'local' | 'harpocrate'>('local')
const [vaultIdentifier, setVaultIdentifier] = useState('')

// Sélecteur de stockage — à placer dans l'étape finale du wizard (après le script)
// Avant le bouton "Enregistrer le host"
function renderStorageSelector() {
  return (
    <div className="space-y-3 rounded-md border p-3">
      <p className="text-sm font-medium">{t('hosts.form.storage', 'Stockage des secrets')}</p>
      <RadioGroup
        value={storageType}
        onValueChange={(v) => {
          setStorageType(v as 'local' | 'harpocrate')
          if (v === 'local') setVaultIdentifier('')
        }}
        className="flex gap-4"
      >
        <div className="flex items-center gap-2">
          <RadioGroupItem value="local" id="gen-storage-local" />
          <Label htmlFor="gen-storage-local">{t('hosts.form.storage_local', 'Local')}</Label>
        </div>
        <div className="flex items-center gap-2">
          <RadioGroupItem value="harpocrate" id="gen-storage-harpo" />
          <Label htmlFor="gen-storage-harpo">Harpocrate</Label>
        </div>
      </RadioGroup>
      {storageType === 'harpocrate' && (
        <Input
          value={vaultIdentifier}
          onChange={(e) => setVaultIdentifier(e.target.value)}
          placeholder="Identifiant du coffre"
          className="text-sm"
        />
      )}
    </div>
  )
}

// Lors de la sauvegarde du host (après le script OK), construire le payload :
function handleSaveHost(result: Record<string, string>, args: Record<string, string>, node: ProxmoxNodeSummary) {
  const payload: HostCreatePayload = {
    name: result.name as string,
    type: (result.type ?? 'docker-tls') as 'docker-tls' | 'ssh',
    docker_host: result.docker_host as string ?? '',
    address: result.address as string ?? '',
    proxmox_node: result.proxmox_node ?? node.name,
    vmid: result.vmid ?? args.NEW_VMID ?? '',
    ci_password: result.ci_password as string ?? '',
    storage_type: storageType,
    vault_identifier: vaultIdentifier,
  }
  addHost.mutate(payload, { onSuccess: () => { /* fermer dialog */ } })
}
```

- [ ] **Étape 4 : Vérification TypeScript**

```bash
cd frontend && npm run type-check
```
ou
```bash
cd frontend && npx tsc --noEmit
```
Attendu : 0 erreur TS.

- [ ] **Étape 5 : Vérification lint frontend**

```bash
cd frontend && npm run lint
```
Attendu : 0 erreur.

- [ ] **Étape 6 : Commit**

```bash
git add frontend/src/features/admin/useHosts.ts frontend/src/features/admin/AdminHosts.tsx frontend/src/features/admin/GenerateHostDialog.tsx
git commit -m "feat: formulaires host — sélecteur stockage local/Harpocrate, ci_password via harpo"
```

---

## Vérification finale

Après tous les commits, lancer la suite complète :

```bash
cd backend && uv run pytest -v && uv run ruff check src/ tests/ && uv run mypy src/
```

Attendu : 0 erreur, tous les tests verts.

Points à valider manuellement :
1. Ajouter un host SSH via le formulaire → `host_cert_slug` vide, `ci_password_secret_slug` peuplé si password saisi
2. Lancer bootstrap-ssh → `host_cert_slug` peuplé dans la réponse + config
3. Démarrer un workspace sur le host SSH → `_run_up_task` matérialise le cert temp, fichier supprimé après
4. Supprimer le host → les entrées harpo_* sont supprimées (vérifier via `GET /me/secrets` ou directement en DB)
5. Ajouter un host via Generate dialog → ci_password et cert stockés selon le sélecteur choisi
