# Profiles VSCode CRUD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implémenter le CRUD des profils VSCode (YAML, portée partagé/user, fork) avec un éditeur frontend embarquant le PluginBrowser existant.

**Architecture:** Backend FastAPI avec deux APIRouter (user sous `/profiles`, admin sous `/admin/profiles`), repository YAML à écriture atomique (pas de DB), frontend React avec liste des profils + éditeur qui réutilise le composant contrôlé `PluginBrowser` sans le modifier.

**Tech Stack:** Python 3.12 + FastAPI + pydantic v2 + pyyaml + pytest-asyncio ; React 18 + TypeScript strict + TanStack Query + shadcn/ui + i18next + MSW + Vitest.

---

## Structure des fichiers

### Backend (créer)
- `backend/src/portal/profiles/__init__.py` — package vide
- `backend/src/portal/profiles/models.py` — Pydantic models (ProfileBody, Profile, ProfileSummary, Scope) + `to_customizations()`
- `backend/src/portal/profiles/repository.py` — ProfileRepository + ProfileError + slugify + écriture atomique
- `backend/src/portal/routes/profiles.py` — router user + router_admin
- `backend/tests/profiles/__init__.py` — package vide
- `backend/tests/profiles/test_repository.py` — tests repository sur tmp_path
- `backend/tests/routes/test_profiles.py` — tests routes HTTP

### Backend (modifier)
- `backend/src/portal/app.py` — inclure les deux routers profiles

### Frontend (créer)
- `frontend/src/features/profiles/api/profiles.ts` — types TS + fonctions apiFetchJson
- `frontend/src/features/profiles/hooks/useProfiles.ts` — useQuery + mutations + invalidation
- `frontend/src/features/profiles/ProfileList.tsx` — liste avec sections Mes/Partagés
- `frontend/src/features/profiles/ProfileEditor.tsx` — éditeur avec PluginBrowser embarqué
- `frontend/src/features/admin/AdminProfiles.tsx` — admin profils partagés
- `frontend/src/features/profiles/__tests__/ProfileList.test.tsx`
- `frontend/src/features/profiles/__tests__/ProfileEditor.test.tsx`

### Frontend (modifier)
- `frontend/vite.config.ts` — ajouter proxy `/profiles`
- `frontend/src/test/handlers.ts` — handlers MSW profiles + admin/profiles
- `frontend/src/router.tsx` — remplacer PluginBrowserPage, ajouter /profiles/new, /profiles/:slug, /admin/profiles
- `frontend/src/shared/layouts/AppShell.tsx` — ajouter entrée admin "Profils partagés"
- `frontend/src/i18n/fr.json` — clés profiles.* + common.save/cancel
- `frontend/src/i18n/en.json` — même clés en anglais

### Frontend (supprimer)
- `frontend/src/features/profiles/PluginBrowserPage.tsx` — remplacée par ProfileList

---

## Task 1 : Backend — modèles Pydantic

**Files:**
- Create: `backend/src/portal/profiles/__init__.py`
- Create: `backend/src/portal/profiles/models.py`
- Test: `backend/tests/profiles/__init__.py` + `backend/tests/profiles/test_repository.py` (étape 1 seulement)

- [ ] **Step 1 : Créer les packages**

```bash
mkdir backend/src/portal/profiles
touch backend/src/portal/profiles/__init__.py
mkdir backend/tests/profiles
touch backend/tests/profiles/__init__.py
```

- [ ] **Step 2 : Écrire le test de sérialisation (rouge)**

Crée `backend/tests/profiles/test_repository.py` avec uniquement :

```python
"""Tests du ProfileRepository sur un répertoire temporaire."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from portal.profiles.models import Profile, ProfileBody, ProfileSummary, Scope
from portal.profiles.repository import ProfileRepository, ProfileError, slugify


def test_slugify_basic() -> None:
    assert slugify("Frontend React") == "frontend-react"


def test_slugify_special_chars() -> None:
    assert slugify("React + TypeScript!") == "react-typescript"


def test_slugify_empty_fallback() -> None:
    assert slugify("!!!") == "profil"


def test_profile_body_defaults() -> None:
    body = ProfileBody(name="Test")
    assert body.description == ""
    assert body.extensions == []
    assert body.settings == {}


def test_profile_to_customizations() -> None:
    profile = Profile(
        slug="test",
        scope="user",
        name="Test",
        extensions=["ms-python.python"],
        settings={"editor.fontSize": 14},
    )
    result = profile.to_customizations()
    assert result == {
        "vscode": {
            "extensions": ["ms-python.python"],
            "settings": {"editor.fontSize": 14},
        }
    }
```

- [ ] **Step 3 : Vérifier que le test échoue**

```bash
cd backend && uv run pytest tests/profiles/test_repository.py -v
```

Attendu : `ImportError: cannot import name 'Profile' from 'portal.profiles.models'`

- [ ] **Step 4 : Implémenter models.py**

Crée `backend/src/portal/profiles/models.py` :

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Scope = Literal["shared", "user"]


class ProfileBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    extensions: list[str] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)


class Profile(ProfileBody):
    slug: str
    scope: Scope

    def to_customizations(self) -> dict[str, Any]:
        return {"vscode": {"extensions": self.extensions, "settings": self.settings}}


class ProfileSummary(BaseModel):
    slug: str
    scope: Scope
    name: str
    description: str
    extension_count: int
    editable: bool
```

- [ ] **Step 5 : Vérifier que le test passe (partiellement — slugify et ProfileRepository manquent)**

```bash
cd backend && uv run pytest tests/profiles/test_repository.py::test_profile_body_defaults tests/profiles/test_repository.py::test_profile_to_customizations -v
```

Attendu : 2 PASS (les tests slugify/repository échouent encore — c'est normal, Task 2)

- [ ] **Step 6 : Commit**

```bash
git add backend/src/portal/profiles/ backend/tests/profiles/
git commit -m "feat(profiles): modèles Pydantic ProfileBody Profile ProfileSummary"
```

---

## Task 2 : Backend — ProfileRepository

**Files:**
- Create: `backend/src/portal/profiles/repository.py`
- Modify: `backend/tests/profiles/test_repository.py` (ajouter tous les tests)

- [ ] **Step 1 : Compléter les tests du repository**

Remplace le contenu de `backend/tests/profiles/test_repository.py` par :

```python
"""Tests du ProfileRepository sur un répertoire temporaire."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from portal.profiles.models import Profile, ProfileBody, ProfileSummary
from portal.profiles.repository import ProfileRepository, ProfileError, slugify


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------

def test_slugify_basic() -> None:
    assert slugify("Frontend React") == "frontend-react"


def test_slugify_special_chars() -> None:
    assert slugify("React + TypeScript!") == "react-typescript"


def test_slugify_empty_fallback() -> None:
    assert slugify("!!!") == "profil"


# ---------------------------------------------------------------------------
# Modèles
# ---------------------------------------------------------------------------

def test_profile_body_defaults() -> None:
    body = ProfileBody(name="Test")
    assert body.description == ""
    assert body.extensions == []
    assert body.settings == {}


def test_profile_to_customizations() -> None:
    profile = Profile(
        slug="test",
        scope="user",
        name="Test",
        extensions=["ms-python.python"],
        settings={"editor.fontSize": 14},
    )
    result = profile.to_customizations()
    assert result == {
        "vscode": {
            "extensions": ["ms-python.python"],
            "settings": {"editor.fontSize": 14},
        }
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path: Path) -> ProfileRepository:
    return ProfileRepository(tmp_path)


ALICE = "alice"
BOB = "bob"

BODY = ProfileBody(name="Frontend React", extensions=["esbenp.prettier-vscode"])


# ---------------------------------------------------------------------------
# create user
# ---------------------------------------------------------------------------

def test_create_writes_yaml_file(repo: ProfileRepository) -> None:
    profile = repo.create(ALICE, BODY)
    assert profile.slug == "frontend-react"
    assert profile.scope == "user"
    path = repo._path("user", "frontend-react", ALICE)
    assert path.is_file()
    raw = yaml.safe_load(path.read_text())
    assert raw["name"] == "Frontend React"
    assert raw["extensions"] == ["esbenp.prettier-vscode"]


def test_create_slug_collision_appends_suffix(repo: ProfileRepository) -> None:
    p1 = repo.create(ALICE, BODY)
    p2 = repo.create(ALICE, BODY)
    assert p1.slug == "frontend-react"
    assert p2.slug == "frontend-react-2"


def test_create_user_isolation(repo: ProfileRepository) -> None:
    repo.create(ALICE, BODY)
    repo.create(BOB, BODY)
    assert repo._path("user", "frontend-react", ALICE).is_file()
    assert repo._path("user", "frontend-react", BOB).is_file()
    # Bob ne voit pas les profils d'Alice via list()
    alice_profiles = [p.slug for p in repo.list(ALICE, False) if p.scope == "user"]
    bob_profiles = [p.slug for p in repo.list(BOB, False) if p.scope == "user"]
    assert "frontend-react" in alice_profiles
    assert "frontend-react" in bob_profiles
    # Mais Alice ne peut pas modifier le profil de Bob
    with pytest.raises(ProfileError) as exc:
        repo.update(ALICE, "frontend-react-bob-fake", BODY)
    assert exc.value.code == "not_found"


# ---------------------------------------------------------------------------
# update user
# ---------------------------------------------------------------------------

def test_update_modifies_yaml(repo: ProfileRepository) -> None:
    repo.create(ALICE, BODY)
    updated_body = ProfileBody(name="Frontend React", description="Updated", extensions=[])
    result = repo.update(ALICE, "frontend-react", updated_body)
    assert result.description == "Updated"
    assert result.extensions == []
    raw = yaml.safe_load(repo._path("user", "frontend-react", ALICE).read_text())
    assert raw["description"] == "Updated"


def test_update_not_found_raises(repo: ProfileRepository) -> None:
    with pytest.raises(ProfileError) as exc:
        repo.update(ALICE, "nonexistent", BODY)
    assert exc.value.code == "not_found"


# ---------------------------------------------------------------------------
# delete user
# ---------------------------------------------------------------------------

def test_delete_removes_file(repo: ProfileRepository) -> None:
    repo.create(ALICE, BODY)
    repo.delete(ALICE, "frontend-react")
    assert not repo._path("user", "frontend-react", ALICE).is_file()


def test_delete_not_found_raises(repo: ProfileRepository) -> None:
    with pytest.raises(ProfileError) as exc:
        repo.delete(ALICE, "nonexistent")
    assert exc.value.code == "not_found"


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------

def test_get_returns_profile(repo: ProfileRepository) -> None:
    repo.create(ALICE, BODY)
    profile = repo.get("user", "frontend-react", ALICE)
    assert profile.slug == "frontend-react"
    assert profile.scope == "user"
    assert profile.name == "Frontend React"


def test_get_not_found_raises(repo: ProfileRepository) -> None:
    with pytest.raises(ProfileError) as exc:
        repo.get("user", "nonexistent", ALICE)
    assert exc.value.code == "not_found"


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def test_list_includes_user_and_shared(repo: ProfileRepository) -> None:
    repo.create(ALICE, BODY)
    repo.create_shared(ProfileBody(name="Shared Profile"))
    summaries = repo.list(ALICE, is_admin=False)
    scopes = {s.scope for s in summaries}
    assert "user" in scopes
    assert "shared" in scopes


def test_list_editable_flag(repo: ProfileRepository) -> None:
    repo.create(ALICE, BODY)
    repo.create_shared(ProfileBody(name="Shared"))
    for s in repo.list(ALICE, is_admin=False):
        if s.scope == "user":
            assert s.editable is True
        else:
            assert s.editable is False


def test_list_editable_admin_can_edit_shared(repo: ProfileRepository) -> None:
    repo.create_shared(ProfileBody(name="Shared"))
    for s in repo.list(ALICE, is_admin=True):
        if s.scope == "shared":
            assert s.editable is True


# ---------------------------------------------------------------------------
# fork
# ---------------------------------------------------------------------------

def test_fork_creates_independent_copy(repo: ProfileRepository) -> None:
    shared_body = ProfileBody(name="Shared", extensions=["ms-python.python"])
    repo.create_shared(shared_body)
    forked = repo.fork(ALICE, "shared")
    assert forked.scope == "user"
    assert forked.extensions == ["ms-python.python"]
    # Modifier le partagé n'affecte pas le fork
    repo.update_shared("shared", ProfileBody(name="Shared", extensions=["new.ext"]))
    forked_again = repo.get("user", forked.slug, ALICE)
    assert forked_again.extensions == ["ms-python.python"]


def test_fork_not_found_raises(repo: ProfileRepository) -> None:
    with pytest.raises(ProfileError) as exc:
        repo.fork(ALICE, "nonexistent")
    assert exc.value.code == "not_found"


# ---------------------------------------------------------------------------
# shared (admin)
# ---------------------------------------------------------------------------

def test_create_shared_writes_to_data_profiles(repo: ProfileRepository) -> None:
    profile = repo.create_shared(ProfileBody(name="Partagé"))
    assert profile.slug == "partage"
    assert profile.scope == "shared"
    assert (repo._data / "profiles" / "partage.yaml").is_file()


def test_update_shared_not_found_raises(repo: ProfileRepository) -> None:
    with pytest.raises(ProfileError) as exc:
        repo.update_shared("nonexistent", BODY)
    assert exc.value.code == "not_found"


def test_delete_shared_removes_file(repo: ProfileRepository) -> None:
    repo.create_shared(ProfileBody(name="To Delete"))
    repo.delete_shared("to-delete")
    assert not (repo._data / "profiles" / "to-delete.yaml").is_file()


# ---------------------------------------------------------------------------
# écriture atomique
# ---------------------------------------------------------------------------

def test_atomic_write_no_tmp_residual(repo: ProfileRepository) -> None:
    repo.create(ALICE, BODY)
    tmp_files = list((repo._data / "users" / ALICE / "profiles").glob("*.tmp"))
    assert tmp_files == []
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
cd backend && uv run pytest tests/profiles/test_repository.py -v 2>&1 | head -20
```

Attendu : `ImportError: cannot import name 'ProfileRepository' from 'portal.profiles.repository'`

- [ ] **Step 3 : Implémenter repository.py**

Crée `backend/src/portal/profiles/repository.py` :

```python
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import structlog
import yaml

from .models import Profile, ProfileBody, ProfileSummary, Scope

_log = structlog.get_logger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return slug or "profil"


class ProfileError(Exception):
    def __init__(self, code: str) -> None:  # "not_found" | "conflict" | "forbidden"
        super().__init__(code)
        self.code = code


class ProfileRepository:
    def __init__(self, data_dir: Path) -> None:
        self._data = data_dir

    def _dir(self, scope: Scope, login: str | None) -> Path:
        if scope == "shared":
            return self._data / "profiles"
        if not login:
            raise ProfileError("forbidden")
        return self._data / "users" / login / "profiles"

    def _path(self, scope: Scope, slug: str, login: str | None) -> Path:
        return self._dir(scope, login) / f"{slug}.yaml"

    def list(self, login: str, is_admin: bool) -> list[ProfileSummary]:
        out: list[ProfileSummary] = []
        for scope, base in (
            ("shared", self._dir("shared", None)),
            ("user", self._dir("user", login)),
        ):
            if not base.is_dir():
                continue
            for f in sorted(base.glob("*.yaml")):
                p = self._read(f, scope, f.stem)  # type: ignore[arg-type]
                editable = is_admin if scope == "shared" else True
                out.append(
                    ProfileSummary(
                        slug=p.slug,
                        scope=p.scope,
                        name=p.name,
                        description=p.description,
                        extension_count=len(p.extensions),
                        editable=editable,
                    )
                )
        return out

    def get(self, scope: Scope, slug: str, login: str) -> Profile:
        path = self._path(scope, slug, None if scope == "shared" else login)
        if not path.is_file():
            raise ProfileError("not_found")
        return self._read(path, scope, slug)

    def create(self, login: str, body: ProfileBody) -> Profile:
        return self._write("user", login, slugify(body.name), body, allow_overwrite=False)

    def update(self, login: str, slug: str, body: ProfileBody) -> Profile:
        if not self._path("user", slug, login).is_file():
            raise ProfileError("not_found")
        return self._write("user", login, slug, body, allow_overwrite=True)

    def delete(self, login: str, slug: str) -> None:
        path = self._path("user", slug, login)
        if not path.is_file():
            raise ProfileError("not_found")
        path.unlink()

    def fork(self, login: str, shared_slug: str) -> Profile:
        src = self.get("shared", shared_slug, login)
        body = ProfileBody(
            **src.model_dump(include={"name", "description", "extensions", "settings"})
        )
        return self._write("user", login, slugify(src.name), body, allow_overwrite=False)

    def create_shared(self, body: ProfileBody) -> Profile:
        return self._write("shared", None, slugify(body.name), body, allow_overwrite=False)

    def update_shared(self, slug: str, body: ProfileBody) -> Profile:
        if not self._path("shared", slug, None).is_file():
            raise ProfileError("not_found")
        return self._write("shared", None, slug, body, allow_overwrite=True)

    def delete_shared(self, slug: str) -> None:
        path = self._path("shared", slug, None)
        if not path.is_file():
            raise ProfileError("not_found")
        path.unlink()

    def _read(self, path: Path, scope: Scope, slug: str) -> Profile:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return Profile(slug=slug, scope=scope, **ProfileBody(**raw).model_dump())

    def _write(
        self,
        scope: Scope,
        login: str | None,
        slug: str,
        body: ProfileBody,
        *,
        allow_overwrite: bool,
    ) -> Profile:
        base = self._dir(scope, login)
        base.mkdir(parents=True, exist_ok=True)
        slug = self._unique_slug(base, slug, allow_overwrite)
        path = base / f"{slug}.yaml"
        self._atomic_dump(path, body)
        _log.info("profile.write", scope=scope, slug=slug)
        return Profile(slug=slug, scope=scope, **body.model_dump())

    @staticmethod
    def _unique_slug(base: Path, slug: str, allow_overwrite: bool) -> str:
        if allow_overwrite or not (base / f"{slug}.yaml").exists():
            return slug
        i = 2
        while (base / f"{slug}-{i}.yaml").exists():
            i += 1
        return f"{slug}-{i}"

    @staticmethod
    def _atomic_dump(path: Path, body: ProfileBody) -> None:
        data = yaml.safe_dump(body.model_dump(), allow_unicode=True, sort_keys=False)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
```

- [ ] **Step 4 : Vérifier que tous les tests passent**

```bash
cd backend && uv run pytest tests/profiles/test_repository.py -v
```

Attendu : tous PASS

- [ ] **Step 5 : Lint + mypy**

```bash
cd backend && uv run ruff check src/portal/profiles/ && uv run mypy src/portal/profiles/
```

Attendu : pas d'erreur

- [ ] **Step 6 : Commit**

```bash
git add backend/src/portal/profiles/repository.py backend/tests/profiles/test_repository.py
git commit -m "feat(profiles): ProfileRepository YAML atomique + tests (slugify, CRUD, fork, isolation)"
```

---

## Task 3 : Backend — Routes user + app.py

**Files:**
- Create: `backend/src/portal/routes/profiles.py`
- Create: `backend/tests/routes/test_profiles.py`
- Modify: `backend/src/portal/app.py`

- [ ] **Step 1 : Écrire les tests des routes user (rouge)**

Crée `backend/tests/routes/test_profiles.py` :

```python
"""Tests des routes /profiles/* et /admin/profiles/* via ASGITransport."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from portal.auth.rbac import UserInfo, require_admin, require_user
from portal.profiles.models import Profile, ProfileBody, ProfileSummary
from portal.profiles.repository import ProfileError, ProfileRepository
from portal.routes.profiles import get_repo, router, router_admin

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ALICE_USER = UserInfo(login="alice", roles=["dev"])
ADMIN_USER = UserInfo(login="admin", roles=["admin"])

MOCK_SUMMARY = ProfileSummary(
    slug="frontend-react",
    scope="user",
    name="Frontend React",
    description="",
    extension_count=1,
    editable=True,
)

MOCK_PROFILE = Profile(
    slug="frontend-react",
    scope="user",
    name="Frontend React",
    description="",
    extensions=["esbenp.prettier-vscode"],
    settings={},
)


@pytest.fixture
def mock_repo() -> MagicMock:
    return MagicMock(spec=ProfileRepository)


@pytest.fixture
def profiles_app(mock_repo: MagicMock) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.include_router(router_admin, prefix="/admin")
    app.dependency_overrides[require_user] = lambda: ALICE_USER
    app.dependency_overrides[require_admin] = lambda: ADMIN_USER
    app.dependency_overrides[get_repo] = lambda: mock_repo
    return app


@pytest.fixture
async def client(profiles_app: FastAPI) -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=profiles_app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# GET /profiles
# ---------------------------------------------------------------------------

async def test_list_returns_200(client: AsyncClient, mock_repo: MagicMock) -> None:
    mock_repo.list.return_value = [MOCK_SUMMARY]
    response = await client.get("/profiles")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["slug"] == "frontend-react"
    mock_repo.list.assert_called_once_with("alice", False)


# ---------------------------------------------------------------------------
# GET /profiles/{scope}/{slug}
# ---------------------------------------------------------------------------

async def test_get_returns_profile(client: AsyncClient, mock_repo: MagicMock) -> None:
    mock_repo.get.return_value = MOCK_PROFILE
    response = await client.get("/profiles/user/frontend-react")
    assert response.status_code == 200
    assert response.json()["slug"] == "frontend-react"


async def test_get_not_found_returns_404(client: AsyncClient, mock_repo: MagicMock) -> None:
    mock_repo.get.side_effect = ProfileError("not_found")
    response = await client.get("/profiles/user/nonexistent")
    assert response.status_code == 404


async def test_get_invalid_scope_returns_422(client: AsyncClient) -> None:
    response = await client.get("/profiles/invalid/slug")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /profiles
# ---------------------------------------------------------------------------

async def test_create_returns_201(client: AsyncClient, mock_repo: MagicMock) -> None:
    mock_repo.create.return_value = MOCK_PROFILE
    response = await client.post(
        "/profiles",
        json={"name": "Frontend React", "extensions": ["esbenp.prettier-vscode"]},
    )
    assert response.status_code == 201
    assert response.json()["slug"] == "frontend-react"


# ---------------------------------------------------------------------------
# PUT /profiles/{slug}
# ---------------------------------------------------------------------------

async def test_update_returns_200(client: AsyncClient, mock_repo: MagicMock) -> None:
    mock_repo.update.return_value = MOCK_PROFILE
    response = await client.put(
        "/profiles/frontend-react",
        json={"name": "Frontend React", "extensions": []},
    )
    assert response.status_code == 200


async def test_update_not_found_returns_404(client: AsyncClient, mock_repo: MagicMock) -> None:
    mock_repo.update.side_effect = ProfileError("not_found")
    response = await client.put(
        "/profiles/nonexistent",
        json={"name": "X", "extensions": []},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /profiles/{slug}
# ---------------------------------------------------------------------------

async def test_delete_returns_204(client: AsyncClient, mock_repo: MagicMock) -> None:
    mock_repo.delete.return_value = None
    response = await client.delete("/profiles/frontend-react")
    assert response.status_code == 204


async def test_delete_not_found_returns_404(client: AsyncClient, mock_repo: MagicMock) -> None:
    mock_repo.delete.side_effect = ProfileError("not_found")
    response = await client.delete("/profiles/nonexistent")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /profiles/shared/{slug}/fork
# ---------------------------------------------------------------------------

async def test_fork_returns_201(client: AsyncClient, mock_repo: MagicMock) -> None:
    forked = Profile(
        slug="frontend-react-2",
        scope="user",
        name="Frontend React",
        description="",
        extensions=["esbenp.prettier-vscode"],
        settings={},
    )
    mock_repo.fork.return_value = forked
    response = await client.post("/profiles/shared/frontend-react/fork")
    assert response.status_code == 201
    assert response.json()["scope"] == "user"
    mock_repo.fork.assert_called_once_with("alice", "frontend-react")


async def test_fork_not_found_returns_404(client: AsyncClient, mock_repo: MagicMock) -> None:
    mock_repo.fork.side_effect = ProfileError("not_found")
    response = await client.post("/profiles/shared/nonexistent/fork")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Routes admin
# ---------------------------------------------------------------------------

async def test_admin_create_shared_returns_201(client: AsyncClient, mock_repo: MagicMock) -> None:
    shared = Profile(
        slug="shared-profile",
        scope="shared",
        name="Shared",
        description="",
        extensions=[],
        settings={},
    )
    mock_repo.create_shared.return_value = shared
    response = await client.post("/admin/profiles", json={"name": "Shared", "extensions": []})
    assert response.status_code == 201
    assert response.json()["scope"] == "shared"


async def test_admin_update_shared_returns_200(client: AsyncClient, mock_repo: MagicMock) -> None:
    shared = Profile(
        slug="shared-profile",
        scope="shared",
        name="Shared Updated",
        description="",
        extensions=[],
        settings={},
    )
    mock_repo.update_shared.return_value = shared
    response = await client.put(
        "/admin/profiles/shared-profile",
        json={"name": "Shared Updated", "extensions": []},
    )
    assert response.status_code == 200


async def test_admin_delete_shared_returns_204(client: AsyncClient, mock_repo: MagicMock) -> None:
    mock_repo.delete_shared.return_value = None
    response = await client.delete("/admin/profiles/shared-profile")
    assert response.status_code == 204
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
cd backend && uv run pytest tests/routes/test_profiles.py -v 2>&1 | head -10
```

Attendu : `ImportError: cannot import name 'get_repo' from 'portal.routes.profiles'`

- [ ] **Step 3 : Implémenter routes/profiles.py**

Crée `backend/src/portal/routes/profiles.py` :

```python
"""Routes CRUD des profils VSCode.

Deux routers :
- router       : préfixe /profiles  (user, monté sans préfixe dans app.py)
- router_admin : préfixe /profiles  (admin, monté sous /admin dans app.py → /admin/profiles)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path

from ..auth.rbac import UserInfo, require_admin, require_user
from ..profiles.models import Profile, ProfileBody, ProfileSummary, Scope
from ..profiles.repository import ProfileError, ProfileRepository
from ..settings import get_settings

# ── Dépendance du repository ────────────────────────────────────────────────

def get_repo() -> ProfileRepository:
    """Remplacée par dependency_overrides dans le lifespan et les tests."""
    raise NotImplementedError  # pragma: no cover


_SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]*$"

# ── Router user ─────────────────────────────────────────────────────────────

router = APIRouter(prefix="/profiles", tags=["profiles"])


def _http(e: ProfileError) -> HTTPException:
    mapping = {"not_found": 404, "conflict": 409, "forbidden": 403}
    return HTTPException(status_code=mapping.get(e.code, 400), detail=e.code)


@router.get("", response_model=list[ProfileSummary])
async def list_profiles(
    user: UserInfo = Depends(require_user),
    repo: ProfileRepository = Depends(get_repo),
) -> list[ProfileSummary]:
    is_admin = "admin" in user.roles
    return repo.list(user.login, is_admin)


# IMPORTANT : /shared/{slug}/fork DOIT être déclaré avant /{scope}/{slug}
# pour éviter que FastAPI capte "shared" comme valeur de {scope} et "slug/fork"
# comme slug invalide.
@router.post("/shared/{slug}/fork", response_model=Profile, status_code=201)
async def fork_profile(
    slug: str = Path(pattern=_SLUG_PATTERN),
    user: UserInfo = Depends(require_user),
    repo: ProfileRepository = Depends(get_repo),
) -> Profile:
    try:
        return repo.fork(user.login, slug)
    except ProfileError as e:
        raise _http(e)


@router.get("/{scope}/{slug}", response_model=Profile)
async def get_profile(
    scope: Scope,
    slug: str = Path(pattern=_SLUG_PATTERN),
    user: UserInfo = Depends(require_user),
    repo: ProfileRepository = Depends(get_repo),
) -> Profile:
    try:
        return repo.get(scope, slug, user.login)
    except ProfileError as e:
        raise _http(e)


@router.post("", response_model=Profile, status_code=201)
async def create_profile(
    body: ProfileBody,
    user: UserInfo = Depends(require_user),
    repo: ProfileRepository = Depends(get_repo),
) -> Profile:
    return repo.create(user.login, body)


@router.put("/{slug}", response_model=Profile)
async def update_profile(
    slug: str = Path(pattern=_SLUG_PATTERN),
    body: ProfileBody = ...,
    user: UserInfo = Depends(require_user),
    repo: ProfileRepository = Depends(get_repo),
) -> Profile:
    try:
        return repo.update(user.login, slug, body)
    except ProfileError as e:
        raise _http(e)


@router.delete("/{slug}", status_code=204)
async def delete_profile(
    slug: str = Path(pattern=_SLUG_PATTERN),
    user: UserInfo = Depends(require_user),
    repo: ProfileRepository = Depends(get_repo),
) -> None:
    try:
        repo.delete(user.login, slug)
    except ProfileError as e:
        raise _http(e)


# ── Router admin (monté sous /admin dans app.py) ────────────────────────────

router_admin = APIRouter(prefix="/profiles", tags=["profiles"])


@router_admin.post("", response_model=Profile, status_code=201)
async def admin_create_shared(
    body: ProfileBody,
    _user: UserInfo = Depends(require_admin),
    repo: ProfileRepository = Depends(get_repo),
) -> Profile:
    return repo.create_shared(body)


@router_admin.put("/{slug}", response_model=Profile)
async def admin_update_shared(
    slug: str = Path(pattern=_SLUG_PATTERN),
    body: ProfileBody = ...,
    _user: UserInfo = Depends(require_admin),
    repo: ProfileRepository = Depends(get_repo),
) -> Profile:
    try:
        return repo.update_shared(slug, body)
    except ProfileError as e:
        raise _http(e)


@router_admin.delete("/{slug}", status_code=204)
async def admin_delete_shared(
    slug: str = Path(pattern=_SLUG_PATTERN),
    _user: UserInfo = Depends(require_admin),
    repo: ProfileRepository = Depends(get_repo),
) -> None:
    try:
        repo.delete_shared(slug)
    except ProfileError as e:
        raise _http(e)
```

- [ ] **Step 4 : Modifier app.py**

Dans `backend/src/portal/app.py`, ajouter après les imports existants :

```python
from .routes.profiles import get_repo as get_profile_repo
from .routes.profiles import router as profiles_router
from .routes.profiles import router_admin as profiles_admin_router
```

Dans la fonction `create_app()`, ajouter après `app.include_router(plugins_router)` :

```python
app.include_router(profiles_router)
app.include_router(profiles_admin_router, prefix="/admin")
```

Dans `_lifespan`, ajouter après `app.dependency_overrides[get_openvsx] = lambda: client` :

```python
from .profiles.repository import ProfileRepository
settings_obj = get_settings()
data_dir = Path(settings_obj.data_dir)
profile_repo = ProfileRepository(data_dir)
app.dependency_overrides[get_profile_repo] = lambda: profile_repo
```

Note : `get_settings()` renvoie les settings de l'app. `settings_obj.data_dir` est le chemin vers `/data`. Vérifie le nom exact du champ dans `backend/src/portal/settings.py` avant d'écrire ce code.

- [ ] **Step 5 : Vérifier les settings**

```bash
cd backend && grep -n "data_dir\|DATA_DIR" src/portal/settings.py | head -10
```

Adapte le nom du champ dans `_lifespan` selon le résultat.

- [ ] **Step 6 : Vérifier que tous les tests passent**

```bash
cd backend && uv run pytest tests/routes/test_profiles.py tests/profiles/ -v
```

Attendu : tous PASS

- [ ] **Step 7 : Lint + mypy**

```bash
cd backend && uv run ruff check src/portal/routes/profiles.py && uv run mypy src/portal/routes/profiles.py
```

- [ ] **Step 8 : Commit**

```bash
git add backend/src/portal/routes/profiles.py backend/tests/routes/test_profiles.py backend/src/portal/app.py
git commit -m "feat(profiles): routes REST user+admin + intégration app.py"
```

---

## Task 4 : Frontend — proxy Vite + types + API layer + MSW handlers

**Files:**
- Modify: `frontend/vite.config.ts`
- Create: `frontend/src/features/profiles/api/profiles.ts`
- Modify: `frontend/src/test/handlers.ts`

- [ ] **Step 1 : Ajouter le proxy `/profiles` dans vite.config.ts**

Dans `frontend/vite.config.ts`, ajouter dans `proxy` :

```ts
'/profiles': { target: 'http://localhost:8080', changeOrigin: true },
```

Le bloc proxy complet devient :
```ts
proxy: {
  '/auth': { target: 'http://localhost:8080', changeOrigin: true },
  '/me': { target: 'http://localhost:8080', changeOrigin: true },
  '/admin': { target: 'http://localhost:8080', changeOrigin: true },
  '/recipes': { target: 'http://localhost:8080', changeOrigin: true },
  '/plugins': { target: 'http://localhost:8080', changeOrigin: true },
  '/profiles': { target: 'http://localhost:8080', changeOrigin: true },
  '/health': { target: 'http://localhost:8080', changeOrigin: true },
},
```

- [ ] **Step 2 : Créer api/profiles.ts**

Crée `frontend/src/features/profiles/api/profiles.ts` :

```ts
import { apiFetch, apiFetchJson } from '@/shared/api/client'

export type Scope = 'shared' | 'user'

export interface ProfileBody {
  name: string
  description: string
  extensions: string[]
  settings: Record<string, unknown>
}

export interface ProfileSummary {
  slug: string
  scope: Scope
  name: string
  description: string
  extension_count: number
  editable: boolean
}

export interface Profile extends ProfileBody {
  slug: string
  scope: Scope
}

export function listProfiles(): Promise<ProfileSummary[]> {
  return apiFetchJson<ProfileSummary[]>('/profiles')
}

export function getProfile(scope: Scope, slug: string): Promise<Profile> {
  return apiFetchJson<Profile>(`/profiles/${scope}/${encodeURIComponent(slug)}`)
}

export function createProfile(body: ProfileBody): Promise<Profile> {
  return apiFetchJson<Profile>('/profiles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function updateProfile(slug: string, body: ProfileBody): Promise<Profile> {
  return apiFetchJson<Profile>(`/profiles/${encodeURIComponent(slug)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export async function deleteProfile(slug: string): Promise<void> {
  await apiFetch(`/profiles/${encodeURIComponent(slug)}`, { method: 'DELETE' })
}

export function forkProfile(slug: string): Promise<Profile> {
  return apiFetchJson<Profile>(`/profiles/shared/${encodeURIComponent(slug)}/fork`, {
    method: 'POST',
  })
}

// ── Admin ────────────────────────────────────────────────────────────────────

export function listSharedProfiles(): Promise<ProfileSummary[]> {
  return apiFetchJson<ProfileSummary[]>('/admin/profiles')
}

export function createSharedProfile(body: ProfileBody): Promise<Profile> {
  return apiFetchJson<Profile>('/admin/profiles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function updateSharedProfile(slug: string, body: ProfileBody): Promise<Profile> {
  return apiFetchJson<Profile>(`/admin/profiles/${encodeURIComponent(slug)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export async function deleteSharedProfile(slug: string): Promise<void> {
  await apiFetch(`/admin/profiles/${encodeURIComponent(slug)}`, { method: 'DELETE' })
}
```

- [ ] **Step 3 : Ajouter les handlers MSW**

Dans `frontend/src/test/handlers.ts`, ajouter avant la ligne `// Handlers plugins` :

```ts
  // Handlers profiles
  http.get('/profiles', () =>
    HttpResponse.json([
      {
        slug: 'frontend-react',
        scope: 'user',
        name: 'Frontend React',
        description: 'Stack React',
        extension_count: 1,
        editable: true,
      },
      {
        slug: 'python-dev',
        scope: 'shared',
        name: 'Python Dev',
        description: 'Python stack',
        extension_count: 2,
        editable: false,
      },
    ])
  ),
  http.get('/profiles/:scope/:slug', ({ params }) =>
    HttpResponse.json({
      slug: params.slug,
      scope: params.scope,
      name: 'Frontend React',
      description: 'Stack React',
      extensions: ['esbenp.prettier-vscode'],
      settings: {},
    })
  ),
  http.post('/profiles', () =>
    HttpResponse.json(
      {
        slug: 'new-profile',
        scope: 'user',
        name: 'New Profile',
        description: '',
        extensions: [],
        settings: {},
      },
      { status: 201 }
    )
  ),
  http.put('/profiles/:slug', ({ params }) =>
    HttpResponse.json({
      slug: params.slug,
      scope: 'user',
      name: 'Updated',
      description: '',
      extensions: [],
      settings: {},
    })
  ),
  http.delete('/profiles/:slug', () => new HttpResponse(null, { status: 204 })),
  http.post('/profiles/shared/:slug/fork', () =>
    HttpResponse.json(
      {
        slug: 'python-dev-2',
        scope: 'user',
        name: 'Python Dev',
        description: 'Python stack',
        extensions: [],
        settings: {},
      },
      { status: 201 }
    )
  ),
  // Admin profiles
  http.get('/admin/profiles', () =>
    HttpResponse.json([
      {
        slug: 'python-dev',
        scope: 'shared',
        name: 'Python Dev',
        description: 'Python stack',
        extension_count: 2,
        editable: true,
      },
    ])
  ),
  http.post('/admin/profiles', () =>
    HttpResponse.json(
      { slug: 'new-shared', scope: 'shared', name: 'New', description: '', extensions: [], settings: {} },
      { status: 201 }
    )
  ),
  http.put('/admin/profiles/:slug', ({ params }) =>
    HttpResponse.json({
      slug: params.slug,
      scope: 'shared',
      name: 'Updated',
      description: '',
      extensions: [],
      settings: {},
    })
  ),
  http.delete('/admin/profiles/:slug', () => new HttpResponse(null, { status: 204 })),
```

**Attention :** le handler `POST /profiles/shared/:slug/fork` doit être déclaré AVANT `POST /profiles/:slug` si ce dernier existe (ici ce n'est pas le cas). Vérifie l'ordre des handlers si des tests échouent avec des correspondances inattendues.

- [ ] **Step 4 : Vérifier que la suite de tests frontend passe encore**

```bash
cd frontend && npm test -- --run 2>&1 | tail -10
```

Attendu : tous les tests existants passent (63 PASS).

- [ ] **Step 5 : Commit**

```bash
git add frontend/vite.config.ts frontend/src/features/profiles/api/profiles.ts frontend/src/test/handlers.ts
git commit -m "feat(profiles): proxy Vite /profiles + couche API TS + handlers MSW"
```

---

## Task 5 : Frontend — Hooks React Query

**Files:**
- Create: `frontend/src/features/profiles/hooks/useProfiles.ts`

- [ ] **Step 1 : Créer hooks/useProfiles.ts**

Crée `frontend/src/features/profiles/hooks/useProfiles.ts` :

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import {
  createProfile,
  createSharedProfile,
  deleteProfile,
  deleteSharedProfile,
  forkProfile,
  getProfile,
  listProfiles,
  updateProfile,
  updateSharedProfile,
} from '../api/profiles'
import type { ProfileBody, Scope } from '../api/profiles'

const QK = ['profiles'] as const

export function useProfiles() {
  return useQuery({ queryKey: QK, queryFn: listProfiles, staleTime: 30_000 })
}

export function useProfile(scope: Scope, slug?: string) {
  return useQuery({
    queryKey: [...QK, scope, slug],
    queryFn: () => getProfile(scope, slug!),
    enabled: Boolean(slug),
  })
}

export function useSaveProfile() {
  const qc = useQueryClient()
  const { t } = useTranslation()
  return useMutation({
    mutationFn: ({ slug, body }: { slug?: string; body: ProfileBody }) =>
      slug ? updateProfile(slug, body) : createProfile(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
    onError: (err: Error) => toast.error(err.message || t('profiles.errors.save')),
  })
}

export function useDeleteProfile() {
  const qc = useQueryClient()
  const { t } = useTranslation()
  return useMutation({
    mutationFn: deleteProfile,
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
    onError: (err: Error) => toast.error(err.message || t('profiles.errors.delete')),
  })
}

export function useForkProfile() {
  const qc = useQueryClient()
  const { t } = useTranslation()
  return useMutation({
    mutationFn: forkProfile,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QK })
      toast.success(t('profiles.forked'))
    },
    onError: (err: Error) => toast.error(err.message || t('profiles.errors.fork')),
  })
}

// ── Admin ────────────────────────────────────────────────────────────────────

export function useSaveSharedProfile() {
  const qc = useQueryClient()
  const { t } = useTranslation()
  return useMutation({
    mutationFn: ({ slug, body }: { slug?: string; body: ProfileBody }) =>
      slug ? updateSharedProfile(slug, body) : createSharedProfile(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
    onError: (err: Error) => toast.error(err.message || t('profiles.errors.save')),
  })
}

export function useDeleteSharedProfile() {
  const qc = useQueryClient()
  const { t } = useTranslation()
  return useMutation({
    mutationFn: deleteSharedProfile,
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
    onError: (err: Error) => toast.error(err.message || t('profiles.errors.delete')),
  })
}
```

- [ ] **Step 2 : Vérifier que la suite de tests passe**

```bash
cd frontend && npm test -- --run 2>&1 | tail -5
```

Attendu : 63 PASS (aucune régression)

- [ ] **Step 3 : Commit**

```bash
git add frontend/src/features/profiles/hooks/useProfiles.ts
git commit -m "feat(profiles): hooks React Query useProfiles useSaveProfile useDeleteProfile useForkProfile"
```

---

## Task 6 : Frontend — i18n

**Files:**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1 : Ajouter les clés dans fr.json**

Dans `frontend/src/i18n/fr.json`, remplace la section `"profiles"` existante par :

```json
"profiles": {
  "title": "Profils VSCode",
  "new": "Nouveau profil",
  "fork": "Forker",
  "forked": "Profil forké avec succès.",
  "preview": "Aperçu devcontainer.json",
  "fields": {
    "name": "Nom",
    "description": "Description"
  },
  "sections": {
    "mine": "Mes profils",
    "shared": "Profils partagés"
  },
  "delete": {
    "confirm": "Supprimer ce profil ?",
    "description": "Cette action supprime définitivement le profil « {{name}} ».",
    "cancel": "Annuler",
    "confirm_btn": "Supprimer"
  },
  "errors": {
    "load": "Impossible de charger les profils.",
    "save": "Erreur lors de la sauvegarde.",
    "delete": "Erreur lors de la suppression.",
    "fork": "Erreur lors du fork."
  },
  "empty": {
    "mine": "Aucun profil personnel. Créez-en un ou forkez un profil partagé.",
    "shared": "Aucun profil partagé."
  },
  "plugins": {
    "title": "Plugins VSCode",
    "searchPlaceholder": "Rechercher une extension…",
    "empty": "Aucun plugin trouvé.",
    "loadMore": "Charger plus",
    "add": "Ajouter",
    "remove": "Retirer",
    "downloadsLabel": "téléch.",
    "selectedCount_one": "{{count}} plugin sélectionné",
    "selectedCount_other": "{{count}} plugins sélectionnés",
    "sort": {
      "relevance": "Pertinence",
      "popular": "Populaires",
      "recent": "Récents",
      "rating": "Mieux notés"
    },
    "errors": {
      "search": "Impossible de contacter le registre de plugins.",
      "detail": "Impossible de charger les détails du plugin.",
      "readme": "Impossible de charger le README."
    }
  }
},
```

Et dans `"common"` :

```json
"common": {
  "loading": "Chargement…",
  "save": "Enregistrer",
  "cancel": "Annuler"
},
```

Et dans `"admin"`, ajouter après `"sharedRecipes"` :

```json
"sharedProfiles": "Profils partagés",
"profilesEmpty": "Aucun profil partagé.",
"addProfile": "Ajouter un profil",
"editProfile": "Modifier le profil",
```

- [ ] **Step 2 : Ajouter les mêmes clés dans en.json**

Dans `frontend/src/i18n/en.json`, remplace la section `"profiles"` par :

```json
"profiles": {
  "title": "VSCode Profiles",
  "new": "New profile",
  "fork": "Fork",
  "forked": "Profile forked successfully.",
  "preview": "devcontainer.json preview",
  "fields": {
    "name": "Name",
    "description": "Description"
  },
  "sections": {
    "mine": "My profiles",
    "shared": "Shared profiles"
  },
  "delete": {
    "confirm": "Delete this profile?",
    "description": "This will permanently delete profile \"{{name}}\".",
    "cancel": "Cancel",
    "confirm_btn": "Delete"
  },
  "errors": {
    "load": "Could not load profiles.",
    "save": "Error while saving.",
    "delete": "Error while deleting.",
    "fork": "Error while forking."
  },
  "empty": {
    "mine": "No personal profiles yet. Create one or fork a shared profile.",
    "shared": "No shared profiles."
  },
  "plugins": {
    "title": "VSCode Plugins",
    "searchPlaceholder": "Search extensions…",
    "empty": "No plugins found.",
    "loadMore": "Load more",
    "add": "Add",
    "remove": "Remove",
    "downloadsLabel": "dl",
    "selectedCount_one": "{{count}} plugin selected",
    "selectedCount_other": "{{count}} plugins selected",
    "sort": {
      "relevance": "Relevance",
      "popular": "Popular",
      "recent": "Recent",
      "rating": "Highest rated"
    },
    "errors": {
      "search": "Could not reach the plugin registry.",
      "detail": "Could not load plugin details.",
      "readme": "Could not load plugin README."
    }
  }
},
```

Et dans `"common"` :

```json
"common": {
  "loading": "Loading…",
  "save": "Save",
  "cancel": "Cancel"
},
```

Et dans `"admin"` :

```json
"sharedProfiles": "Shared profiles",
"profilesEmpty": "No shared profiles.",
"addProfile": "Add profile",
"editProfile": "Edit profile",
```

- [ ] **Step 3 : Vérifier que les tests passent**

```bash
cd frontend && npm test -- --run 2>&1 | tail -5
```

Attendu : tous les tests existants passent.

- [ ] **Step 4 : Commit**

```bash
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(i18n): clés profiles.* common.save/cancel admin.sharedProfiles fr+en"
```

---

## Task 7 : Frontend — ProfileList

**Files:**
- Create: `frontend/src/features/profiles/ProfileList.tsx`
- Create: `frontend/src/features/profiles/__tests__/ProfileList.test.tsx`

- [ ] **Step 1 : Écrire les tests (rouge)**

Crée `frontend/src/features/profiles/__tests__/ProfileList.test.tsx` :

```tsx
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, beforeEach } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import ProfileList from '../ProfileList'

describe('ProfileList', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev'] } })
  })

  it('affiche les deux sections Mes profils et Partagés', async () => {
    renderWithProviders(<ProfileList />)
    expect(await screen.findByRole('heading', { name: /mes profils|my profiles/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /profils partagés|shared profiles/i })).toBeInTheDocument()
  })

  it('affiche le nom des profils', async () => {
    renderWithProviders(<ProfileList />)
    expect(await screen.findByText('Frontend React')).toBeInTheDocument()
    expect(screen.getByText('Python Dev')).toBeInTheDocument()
  })

  it('affiche le bouton Forker sur les profils partagés', async () => {
    renderWithProviders(<ProfileList />)
    await screen.findByText('Python Dev')
    expect(screen.getByRole('button', { name: /forker|fork/i })).toBeInTheDocument()
  })

  it("n'affiche pas de bouton Forker sur les profils user", async () => {
    renderWithProviders(<ProfileList />)
    await screen.findByText('Frontend React')
    // Le profil user ne doit pas avoir de bouton Fork
    const forkButtons = screen.queryAllByRole('button', { name: /forker|fork/i })
    // Il ne devrait y en avoir qu'un (pour le profil partagé), pas deux
    expect(forkButtons).toHaveLength(1)
  })

  it('affiche le bouton Nouveau profil', async () => {
    renderWithProviders(<ProfileList />)
    await screen.findByText('Frontend React')
    expect(screen.getByRole('link', { name: /nouveau profil|new profile/i })).toBeInTheDocument()
  })

  it('affiche un dialog de confirmation avant suppression', async () => {
    renderWithProviders(<ProfileList />)
    await screen.findByText('Frontend React')
    const deleteBtn = screen.getByRole('button', { name: /supprimer|delete/i })
    await userEvent.click(deleteBtn)
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
cd frontend && npm test -- --run src/features/profiles/__tests__/ProfileList.test.tsx 2>&1 | tail -15
```

Attendu : les tests échouent car `ProfileList` n'existe pas.

- [ ] **Step 3 : Implémenter ProfileList.tsx**

Crée `frontend/src/features/profiles/ProfileList.tsx` :

```tsx
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useProfiles, useDeleteProfile, useForkProfile } from './hooks/useProfiles'
import type { ProfileSummary } from './api/profiles'

export default function ProfileList() {
  const { t } = useTranslation()
  const { data: profiles, isLoading, isError } = useProfiles()
  const deleteMutation = useDeleteProfile()
  const forkMutation = useForkProfile()
  const [confirmDelete, setConfirmDelete] = useState<ProfileSummary | null>(null)

  const mine = profiles?.filter((p) => p.scope === 'user') ?? []
  const shared = profiles?.filter((p) => p.scope === 'shared') ?? []

  function handleDeleteConfirm() {
    if (confirmDelete) {
      deleteMutation.mutate(confirmDelete.slug, { onSuccess: () => setConfirmDelete(null) })
    }
  }

  if (isLoading) return <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
  if (isError) return <p className="text-sm text-destructive">{t('profiles.errors.load')}</p>

  return (
    <div className="flex flex-col gap-8 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t('profiles.title')}</h1>
        <Button asChild size="sm">
          <Link to="/profiles/new">
            <Plus className="mr-1 h-4 w-4" />
            {t('profiles.new')}
          </Link>
        </Button>
      </div>

      {/* Mes profils */}
      <section>
        <h2 className="mb-3 text-lg font-medium">{t('profiles.sections.mine')}</h2>
        {mine.length === 0 && (
          <p className="text-sm text-muted-foreground">{t('profiles.empty.mine')}</p>
        )}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {mine.map((p) => (
            <ProfileCard
              key={p.slug}
              profile={p}
              onDelete={() => setConfirmDelete(p)}
            />
          ))}
        </div>
      </section>

      {/* Profils partagés */}
      <section>
        <h2 className="mb-3 text-lg font-medium">{t('profiles.sections.shared')}</h2>
        {shared.length === 0 && (
          <p className="text-sm text-muted-foreground">{t('profiles.empty.shared')}</p>
        )}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {shared.map((p) => (
            <ProfileCard
              key={p.slug}
              profile={p}
              onFork={() => forkMutation.mutate(p.slug)}
              forkPending={forkMutation.isPending}
            />
          ))}
        </div>
      </section>

      {/* Dialog confirmation suppression */}
      <Dialog open={Boolean(confirmDelete)} onOpenChange={(o) => !o && setConfirmDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('profiles.delete.confirm')}</DialogTitle>
            <DialogDescription>
              {t('profiles.delete.description', { name: confirmDelete?.name })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmDelete(null)}>
              {t('profiles.delete.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeleteConfirm}
              disabled={deleteMutation.isPending}
            >
              {t('profiles.delete.confirm_btn')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

interface CardProps {
  profile: ProfileSummary
  onDelete?: () => void
  onFork?: () => void
  forkPending?: boolean
}

function ProfileCard({ profile, onDelete, onFork, forkPending }: CardProps) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-2 rounded-lg border bg-card p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-medium">{profile.name}</p>
          <p className="text-xs text-muted-foreground">
            {profile.extension_count} extension{profile.extension_count !== 1 ? 's' : ''}
          </p>
        </div>
      </div>
      {profile.description && (
        <p className="line-clamp-2 text-sm text-muted-foreground">{profile.description}</p>
      )}
      <div className="mt-auto flex gap-2 pt-2">
        {profile.editable && (
          <Button size="sm" variant="outline" asChild>
            <Link to={`/profiles/${profile.slug}`}>{t('workspaces.actions.edit')}</Link>
          </Button>
        )}
        {onDelete && (
          <Button size="sm" variant="ghost" className="text-destructive hover:text-destructive" onClick={onDelete}>
            {t('workspaces.actions.delete')}
          </Button>
        )}
        {onFork && (
          <Button size="sm" variant="outline" onClick={onFork} disabled={forkPending}>
            {t('profiles.fork')}
          </Button>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
cd frontend && npm test -- --run src/features/profiles/__tests__/ProfileList.test.tsx 2>&1 | tail -15
```

Attendu : tous les tests ProfileList PASS

- [ ] **Step 5 : Vérifier l'absence de régression**

```bash
cd frontend && npm test -- --run 2>&1 | tail -5
```

Attendu : tous les tests PASS

- [ ] **Step 6 : Commit**

```bash
git add frontend/src/features/profiles/ProfileList.tsx frontend/src/features/profiles/__tests__/ProfileList.test.tsx
git commit -m "feat(profiles): ProfileList — sections Mes/Partagés, fork, suppression avec confirmation"
```

---

## Task 8 : Frontend — ProfileEditor

**Files:**
- Create: `frontend/src/features/profiles/ProfileEditor.tsx`
- Create: `frontend/src/features/profiles/__tests__/ProfileEditor.test.tsx`

- [ ] **Step 1 : Écrire les tests (rouge)**

Crée `frontend/src/features/profiles/__tests__/ProfileEditor.test.tsx` :

```tsx
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, beforeEach } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import ProfileEditor from '../ProfileEditor'

describe('ProfileEditor — création', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev'] } })
  })

  it('affiche les champs name et description vides', () => {
    renderWithProviders(<ProfileEditor />, { route: '/profiles/new' })
    const nameInput = screen.getByLabelText(/nom|name/i)
    const descInput = screen.getByLabelText(/description/i)
    expect(nameInput).toHaveValue('')
    expect(descInput).toHaveValue('')
  })

  it('affiche la preview devcontainer vide initialement', () => {
    renderWithProviders(<ProfileEditor />, { route: '/profiles/new' })
    const pre = screen.getByRole('code')
    expect(pre).toHaveTextContent('"extensions": []')
  })

  it('le bouton Enregistrer est désactivé si le nom est vide', () => {
    renderWithProviders(<ProfileEditor />, { route: '/profiles/new' })
    const saveBtn = screen.getByRole('button', { name: /enregistrer|save/i })
    expect(saveBtn).toBeDisabled()
  })

  it('active le bouton Enregistrer quand le nom est renseigné', async () => {
    renderWithProviders(<ProfileEditor />, { route: '/profiles/new' })
    const nameInput = screen.getByLabelText(/nom|name/i)
    await userEvent.type(nameInput, 'Mon profil')
    const saveBtn = screen.getByRole('button', { name: /enregistrer|save/i })
    expect(saveBtn).not.toBeDisabled()
  })
})

describe('ProfileEditor — édition', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev'] } })
  })

  it('préremplie le nom et la description depuis le profil existant', async () => {
    renderWithProviders(<ProfileEditor />, { route: '/profiles/frontend-react' })
    expect(await screen.findByDisplayValue('Frontend React')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
cd frontend && npm test -- --run src/features/profiles/__tests__/ProfileEditor.test.tsx 2>&1 | tail -10
```

Attendu : erreur car `ProfileEditor` n'existe pas.

- [ ] **Step 3 : Implémenter ProfileEditor.tsx**

Crée `frontend/src/features/profiles/ProfileEditor.tsx` :

```tsx
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PluginBrowser } from './components/PluginBrowser'
import { useProfile, useSaveProfile } from './hooks/useProfiles'

export default function ProfileEditor() {
  const { slug } = useParams<{ slug?: string }>()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const editing = Boolean(slug)

  const { data: existing } = useProfile('user', slug)
  const save = useSaveProfile()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [settings] = useState<Record<string, unknown>>({})

  useEffect(() => {
    if (existing) {
      setName(existing.name)
      setDescription(existing.description)
      setSelected(new Set(existing.extensions))
    }
  }, [existing])

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  const devcontainerPreview = useMemo(
    () =>
      JSON.stringify(
        { customizations: { vscode: { extensions: [...selected], settings } } },
        null,
        2,
      ),
    [selected, settings],
  )

  const onSave = () =>
    save.mutate(
      { slug, body: { name, description, extensions: [...selected], settings } },
      { onSuccess: () => navigate('/profiles') },
    )

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex flex-col gap-3 max-w-xl">
        <Label htmlFor="profile-name">{t('profiles.fields.name')}</Label>
        <Input
          id="profile-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('profiles.fields.name')}
        />
        <Label htmlFor="profile-desc">{t('profiles.fields.description')}</Label>
        <Input
          id="profile-desc"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={t('profiles.fields.description')}
        />
      </div>

      <section>
        <h2 className="mb-2 text-lg font-medium">{t('profiles.plugins.title')}</h2>
        <PluginBrowser selectedIds={selected} onToggle={toggle} />
      </section>

      <section>
        <h2 className="mb-2 text-lg font-medium">{t('profiles.preview')}</h2>
        <pre role="code" className="overflow-x-auto rounded-md bg-muted p-4 text-xs">
          {devcontainerPreview}
        </pre>
      </section>

      <div className="flex gap-2">
        <Button onClick={onSave} disabled={!name.trim() || save.isPending}>
          {t('common.save')}
        </Button>
        <Button variant="ghost" onClick={() => navigate('/profiles')}>
          {t('common.cancel')}
        </Button>
      </div>
    </div>
  )
}
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
cd frontend && npm test -- --run src/features/profiles/__tests__/ProfileEditor.test.tsx 2>&1 | tail -15
```

Attendu : tous les tests ProfileEditor PASS

- [ ] **Step 5 : Vérifier l'absence de régression**

```bash
cd frontend && npm test -- --run 2>&1 | tail -5
```

- [ ] **Step 6 : Commit**

```bash
git add frontend/src/features/profiles/ProfileEditor.tsx frontend/src/features/profiles/__tests__/ProfileEditor.test.tsx
git commit -m "feat(profiles): ProfileEditor — formulaire + PluginBrowser embarqué + preview devcontainer"
```

---

## Task 9 : Frontend — AdminProfiles

**Files:**
- Create: `frontend/src/features/admin/AdminProfiles.tsx`

- [ ] **Step 1 : Créer AdminProfiles.tsx**

Crée `frontend/src/features/admin/AdminProfiles.tsx` :

```tsx
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useProfiles, useSaveSharedProfile, useDeleteSharedProfile } from '@/features/profiles/hooks/useProfiles'
import type { ProfileSummary } from '@/features/profiles/api/profiles'

interface FormState {
  name: string
  description: string
  extensions: string
}

const EMPTY: FormState = { name: '', description: '', extensions: '' }

export default function AdminProfiles() {
  const { t } = useTranslation()
  const { data: profiles, isLoading, isError } = useProfiles()
  const saveMutation = useSaveSharedProfile()
  const deleteMutation = useDeleteSharedProfile()

  const [editingSlug, setEditingSlug] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<FormState>(EMPTY)
  const [confirmDelete, setConfirmDelete] = useState<ProfileSummary | null>(null)

  const shared = profiles?.filter((p) => p.scope === 'shared') ?? []
  const isEditing = editingSlug !== null

  function openCreate() {
    setEditingSlug(null)
    setForm(EMPTY)
    setOpen(true)
  }

  function openEdit(p: ProfileSummary) {
    setEditingSlug(p.slug)
    setForm({ name: p.name, description: p.description, extensions: '' })
    setOpen(true)
  }

  function handleClose() {
    setOpen(false)
    setEditingSlug(null)
    setForm(EMPTY)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const exts = form.extensions
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean)
    const body = { name: form.name, description: form.description, extensions: exts, settings: {} }
    saveMutation.mutate(
      { slug: editingSlug ?? undefined, body },
      { onSuccess: handleClose },
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t('admin.sharedProfiles')}</h2>
        <Button size="sm" onClick={openCreate}>
          <Plus className="mr-1 h-4 w-4" />
          {t('admin.addProfile')}
        </Button>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}
      {!isLoading && !isError && shared.length === 0 && (
        <p className="text-muted-foreground">{t('admin.profilesEmpty')}</p>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {shared.map((p) => (
          <div key={p.slug} className="rounded-lg border bg-card p-4">
            <div className="mb-1 font-medium">{p.name}</div>
            <div className="mb-3 text-xs text-muted-foreground">
              {p.extension_count} extension{p.extension_count !== 1 ? 's' : ''}
            </div>
            <div className="flex gap-1">
              <Button size="sm" variant="ghost" onClick={() => openEdit(p)}>
                {t('workspaces.actions.edit')}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="text-destructive hover:text-destructive"
                onClick={() => setConfirmDelete(p)}
              >
                {t('workspaces.actions.delete')}
              </Button>
            </div>
          </div>
        ))}
      </div>

      {/* Dialog create/edit */}
      <Dialog open={open} onOpenChange={(o) => !o && handleClose()}>
        <DialogContent>
          <form onSubmit={handleSubmit}>
            <DialogHeader>
              <DialogTitle>{isEditing ? t('admin.editProfile') : t('admin.addProfile')}</DialogTitle>
              <DialogDescription className="sr-only">
                {t('admin.editProfile')}
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-3 py-4">
              <Label htmlFor="ap-name">{t('profiles.fields.name')}</Label>
              <Input
                id="ap-name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                required
              />
              <Label htmlFor="ap-desc">{t('profiles.fields.description')}</Label>
              <Input
                id="ap-desc"
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              />
              <Label htmlFor="ap-ext">Extensions (une par ligne)</Label>
              <textarea
                id="ap-ext"
                className="min-h-[80px] w-full rounded-md border bg-background px-3 py-2 text-sm font-mono"
                value={form.extensions}
                onChange={(e) => setForm((f) => ({ ...f, extensions: e.target.value }))}
                placeholder="esbenp.prettier-vscode&#10;dbaeumer.vscode-eslint"
              />
            </div>
            <DialogFooter>
              <Button variant="ghost" type="button" onClick={handleClose}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={!form.name.trim() || saveMutation.isPending}>
                {t('common.save')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Dialog confirmation suppression */}
      <Dialog open={Boolean(confirmDelete)} onOpenChange={(o) => !o && setConfirmDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('profiles.delete.confirm')}</DialogTitle>
            <DialogDescription>
              {t('profiles.delete.description', { name: confirmDelete?.name })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmDelete(null)}>
              {t('profiles.delete.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (confirmDelete) {
                  deleteMutation.mutate(confirmDelete.slug, {
                    onSuccess: () => setConfirmDelete(null),
                  })
                }
              }}
              disabled={deleteMutation.isPending}
            >
              {t('profiles.delete.confirm_btn')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
```

- [ ] **Step 2 : Vérifier que les tests globaux passent**

```bash
cd frontend && npm test -- --run 2>&1 | tail -5
```

Attendu : tous les tests PASS (AdminProfiles n'a pas de tests dédiés — couvert par les handlers MSW existants).

- [ ] **Step 3 : Commit**

```bash
git add frontend/src/features/admin/AdminProfiles.tsx
git commit -m "feat(admin): AdminProfiles — CRUD profils partagés (miroir AdminRecipes)"
```

---

## Task 10 : Routing + navigation + suppression PluginBrowserPage

**Files:**
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/shared/layouts/AppShell.tsx`
- Delete: `frontend/src/features/profiles/PluginBrowserPage.tsx`

- [ ] **Step 1 : Mettre à jour router.tsx**

Remplace le contenu de `frontend/src/router.tsx` par :

```tsx
import { createBrowserRouter, Navigate } from 'react-router-dom'
import { lazy, Suspense } from 'react'
import type { ReactNode } from 'react'
import AppShell from '@/shared/layouts/AppShell'
import AdminGuard from '@/shared/layouts/AdminGuard'
import RequireAuth from '@/features/auth/RequireAuth'
import LoginPage from '@/features/auth/LoginPage'
import AuthCallbackPage from '@/features/auth/AuthCallbackPage'

const WorkspaceList = lazy(() => import('@/features/workspaces/WorkspaceList'))
const WorkspaceCreate = lazy(() => import('@/features/workspaces/WorkspaceCreate'))
const RecipeCatalog = lazy(() => import('@/features/recipes/RecipeCatalog'))
const AdminHosts = lazy(() => import('@/features/admin/AdminHosts'))
const AdminRecipes = lazy(() => import('@/features/admin/AdminRecipes'))
const AdminProxmox = lazy(() => import('@/features/admin/AdminProxmox'))
const AdminHypervisorTypes = lazy(() => import('@/features/admin/AdminHypervisorTypes'))
const AdminProfiles = lazy(() => import('@/features/admin/AdminProfiles'))
const ProfileList = lazy(() => import('@/features/profiles/ProfileList'))
const ProfileEditor = lazy(() => import('@/features/profiles/ProfileEditor'))

function Wrap({ children }: { children: ReactNode }) {
  return <Suspense fallback={null}>{children}</Suspense>
}

export const router = createBrowserRouter([
  { path: '/auth/login', element: <LoginPage /> },
  { path: '/auth/callback', element: <AuthCallbackPage /> },
  {
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/workspaces" replace /> },
      { path: '/workspaces', element: <Wrap><WorkspaceList /></Wrap> },
      { path: '/workspaces/new', element: <Wrap><WorkspaceCreate /></Wrap> },
      { path: '/recipes', element: <Wrap><RecipeCatalog /></Wrap> },
      { path: '/profiles', element: <Wrap><ProfileList /></Wrap> },
      { path: '/profiles/new', element: <Wrap><ProfileEditor /></Wrap> },
      { path: '/profiles/:slug', element: <Wrap><ProfileEditor /></Wrap> },
      {
        path: '/admin/hosts',
        element: <AdminGuard><Wrap><AdminHosts /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/recipes',
        element: <AdminGuard><Wrap><AdminRecipes /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/profiles',
        element: <AdminGuard><Wrap><AdminProfiles /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/hypervisors',
        element: <AdminGuard><Wrap><AdminProxmox /></Wrap></AdminGuard>,
      },
      {
        path: '/admin/hypervisor-types',
        element: <AdminGuard><Wrap><AdminHypervisorTypes /></Wrap></AdminGuard>,
      },
    ],
  },
])
```

- [ ] **Step 2 : Mettre à jour AppShell.tsx — ajouter item admin Profils partagés**

Dans `frontend/src/shared/layouts/AppShell.tsx`, dans le bloc `{isAdmin && (...)}`, ajouter après l'entrée `/admin/recipes` :

```tsx
<DropdownMenuItem onClick={() => navigate('/admin/profiles')}>
  {t('admin.sharedProfiles')}
</DropdownMenuItem>
```

Le bloc complet isAdmin devient :

```tsx
{isAdmin && (
  <>
    <DropdownMenuSeparator />
    <DropdownMenuItem onClick={() => navigate('/admin/hypervisors')}>
      {t('admin.hypervisors')}
    </DropdownMenuItem>
    <DropdownMenuItem onClick={() => navigate('/admin/hypervisor-types')}>
      {t('admin.hypervisorTypes')}
    </DropdownMenuItem>
    <DropdownMenuItem onClick={() => navigate('/admin/hosts')}>
      {t('admin.hosts')}
    </DropdownMenuItem>
    <DropdownMenuItem onClick={() => navigate('/admin/recipes')}>
      {t('admin.sharedRecipes')}
    </DropdownMenuItem>
    <DropdownMenuItem onClick={() => navigate('/admin/profiles')}>
      {t('admin.sharedProfiles')}
    </DropdownMenuItem>
  </>
)}
```

- [ ] **Step 3 : Supprimer PluginBrowserPage.tsx**

```bash
rm frontend/src/features/profiles/PluginBrowserPage.tsx
```

- [ ] **Step 4 : Mettre à jour le titre dans AppShell pour pointer vers profiles.title**

Dans `frontend/src/shared/layouts/AppShell.tsx`, ligne qui affiche le titre du NavLink vers `/profiles`, remplacer :

```tsx
title={t('profiles.plugins.title')}
```

par :

```tsx
title={t('profiles.title')}
```

- [ ] **Step 5 : Vérifier que tous les tests passent**

```bash
cd frontend && npm test -- --run 2>&1 | tail -10
```

Attendu : tous les tests PASS

- [ ] **Step 6 : Vérifier le lint TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Attendu : aucune erreur de type.

- [ ] **Step 7 : Commit**

```bash
git add frontend/src/router.tsx frontend/src/shared/layouts/AppShell.tsx
git rm frontend/src/features/profiles/PluginBrowserPage.tsx
git commit -m "feat(profiles): routing ProfileList+ProfileEditor+AdminProfiles, nav admin, suppression PluginBrowserPage"
```

---

## Task 11 : Vérification finale + settings backend

**Files:**
- Modify: `backend/src/portal/app.py` (finaliser le lifespan avec le bon champ settings)

- [ ] **Step 1 : Vérifier le nom du champ data_dir dans settings.py**

```bash
cd backend && grep -n "data_dir\|DATA_DIR\|data_path" src/portal/settings.py
```

- [ ] **Step 2 : Finaliser le lifespan dans app.py**

Assure-toi que le lifespan dans `app.py` initialise bien le `ProfileRepository`. Le bloc `_lifespan` complet doit ressembler à :

```python
@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    from pathlib import Path
    from .openvsx import OpenVsxClient, OpenVsxSettings
    from .profiles.repository import ProfileRepository
    from .routes.profiles import get_repo as get_profile_repo

    with contextlib.suppress(Exception):
        await _get_service().reconcile_port_forwards()

    settings_obj = get_settings()
    data_dir = Path(settings_obj.data_dir)  # adapter selon le nom réel du champ

    profile_repo = ProfileRepository(data_dir)
    app.dependency_overrides[get_profile_repo] = lambda: profile_repo

    async with httpx.AsyncClient(headers={"User-Agent": "devpod-ui/1.0"}) as http:
        client = OpenVsxClient(OpenVsxSettings(), http)
        app.dependency_overrides[get_openvsx] = lambda: client
        yield
```

Note : adapte `settings_obj.data_dir` au nom réel du champ (étape 1 ci-dessus).

- [ ] **Step 3 : Lancer tous les tests backend**

```bash
cd backend && uv run pytest -v 2>&1 | tail -20
```

Attendu : tous les tests PASS (incluant les tests existants).

- [ ] **Step 4 : Lint + mypy complet**

```bash
cd backend && uv run ruff check src/ && uv run mypy src/
```

- [ ] **Step 5 : Lancer tous les tests frontend**

```bash
cd frontend && npm test -- --run 2>&1 | tail -10
```

Attendu : tous les tests PASS.

- [ ] **Step 6 : Commit final**

```bash
git add backend/src/portal/app.py
git commit -m "chore(profiles): finalisation lifespan — initialisation ProfileRepository dans app.py"
```

---

## Self-Review

### 1. Couverture spec

| Exigence spec | Tâche |
|---|---|
| Repository YAML (partagé + user), atomique, slugify + anti-collision | Task 2 |
| Routes user (list/get/create/update/delete/fork) | Task 3 |
| Routes admin partagées sous require_admin | Task 3 |
| `to_customizations()` livrée et testée | Task 1 (dans models.py) |
| Liste + éditeur ; éditeur embarque PluginBrowser | Task 7, Task 8 |
| Preview devcontainer.json reflète la sélection | Task 8 |
| Route démo retirée ; /profiles = liste | Task 10 |
| Admin partagés miroir des recipes, nav admin | Task 9, Task 10 |
| i18n fr + en complet | Task 6 |
| Tests backend + frontend verts | Tasks 2, 3, 7, 8 |
| Aucun fichier > 300 lignes | ProfileList ~200 l, ProfileEditor ~120 l, AdminProfiles ~280 l ✓ |

### 2. Points d'attention pour l'implémenteur

- **Ordre des routes FastAPI** : `POST /profiles/shared/{slug}/fork` AVANT `GET /profiles/{scope}/{slug}` (commentaire en place dans le code)
- **settings.data_dir** : vérifier le nom exact du champ avant d'écrire le lifespan (Task 11 Step 1)
- **`body: ProfileBody = ...`** dans `update_profile` et `admin_update_shared` : la syntaxe FastAPI pour body obligatoire dans PUT avec path param. Si FastAPI génère une erreur de parsing, utiliser `Annotated[ProfileBody, Body()]` à la place
- **MSW handler fork** : `/profiles/shared/:slug/fork` est déclaré avant `/profiles/:scope/:slug` pour éviter le shadowing
- **`ProfileEditor` en mode édition** : appelle `useProfile('user', slug)` — le handler MSW `/profiles/:scope/:slug` répond avec `name: 'Frontend React'` pour tous les slugs, donc le test de préremplissage trouve bien la valeur
