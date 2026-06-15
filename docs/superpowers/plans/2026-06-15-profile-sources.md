# Profile Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre à un admin de configurer des serveurs de profils distants (via `toc.txt`), de prévisualiser la galerie agrégée, et d'importer des profils partagés — page `/admin/profile-sources` miroir exact d'AdminRecipes.

**Architecture:** Backend `profile_sources.py` calqué sur `recipe_sources.py` existant — même pattern load/save/check_ssrf/preview/import. toc.txt enrichi pipe-délimité (`filename | name | description | extension_count`). Frontend `useProfileSources.ts` + `AdminProfileSources.tsx` miroir de `useRecipeSources.ts` / `AdminRecipes.tsx`.

**Tech Stack:** FastAPI + pydantic v2 + httpx + structlog (backend), React 18 + TanStack Query + shadcn/ui + i18next (frontend), pytest + Vitest + MSW (tests)

---

## Fichiers touchés

| Fichier | Action |
|---|---|
| `backend/src/portal/routes/profile_sources.py` | Créer — routes admin CRUD sources + preview + import |
| `backend/src/portal/app.py` | Modifier — inclure le nouveau router |
| `backend/tests/routes/test_profile_sources.py` | Créer — tests TDD |
| `frontend/src/features/admin/useProfileSources.ts` | Créer — hooks React Query |
| `frontend/src/features/admin/AdminProfileSources.tsx` | Créer — page UI |
| `frontend/src/router.tsx` | Modifier — ajouter route `/admin/profile-sources` |
| `frontend/src/shared/layouts/AppShell.tsx` | Modifier — lien nav admin |
| `frontend/src/i18n/fr.json` | Modifier — clés `admin.profileSources.*` |
| `frontend/src/i18n/en.json` | Modifier — clés `admin.profileSources.*` |
| `frontend/src/test/handlers.ts` | Modifier — handlers MSW |
| `frontend/src/features/admin/AdminProfileSources.test.tsx` | Créer — tests |

---

## Task 1 : Backend — `profile_sources.py` (TDD)

**Files:**
- Create: `backend/src/portal/routes/profile_sources.py`
- Create: `backend/tests/routes/test_profile_sources.py`

### Étape 1 : Écrire les tests (rouge)

Créer `backend/tests/routes/test_profile_sources.py` :

```python
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient


def _make_admin_app(tmp_path: Path):
    import portal.settings as mod
    from portal.routes.workspace_ops import _reset_service

    mod._settings = None
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    mod._settings = None
    _reset_service()

    from portal.app import create_app
    from portal.auth.rbac import UserInfo, require_admin

    app = create_app()
    app.dependency_overrides[require_admin] = lambda: UserInfo(
        login="admin", roles=["admin"]
    )
    return app


def test_get_profile_sources_empty(tmp_path: Path) -> None:
    """Sans fichier profile-sources.yaml, retourne une liste vide."""
    app = _make_admin_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/admin/profile-sources")
    assert resp.status_code == 200
    assert resp.json() == {"sources": []}


def test_put_profile_sources_saves(tmp_path: Path) -> None:
    """PUT /admin/profile-sources sauvegarde les URLs et les relit."""
    app = _make_admin_app(tmp_path)
    urls = ["https://example.com/profiles/"]
    with TestClient(app) as client:
        with patch(
            "portal.routes.profile_sources._check_ssrf", return_value=None
        ):
            resp = client.put(
                "/admin/profile-sources",
                json={"sources": urls},
            )
    assert resp.status_code == 200
    assert resp.json()["sources"] == urls
    saved = yaml.safe_load(
        (tmp_path / "profile-sources.yaml").read_text(encoding="utf-8")
    )
    assert saved["sources"] == urls


def test_put_profile_sources_rejects_http(tmp_path: Path) -> None:
    """PUT /admin/profile-sources rejette les URLs non-HTTPS."""
    app = _make_admin_app(tmp_path)
    with TestClient(app) as client:
        resp = client.put(
            "/admin/profile-sources",
            json={"sources": ["http://example.com/profiles/"]},
        )
    assert resp.status_code == 422


def test_preview_profile_sources(tmp_path: Path) -> None:
    """GET preview fetche toc.txt et retourne les profils disponibles."""
    (tmp_path / "profile-sources.yaml").write_text(
        yaml.dump({"sources": ["https://example.com/profiles/"]}),
        encoding="utf-8",
    )
    toc_content = "python-dev.yaml | Python Dev | Profil Python | 8\n"
    toc_content += "invalid line without pipes\n"

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = toc_content

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    app = _make_admin_app(tmp_path)
    with TestClient(app) as client:
        with patch("portal.routes.profile_sources.httpx.AsyncClient", return_value=mock_client):
            resp = client.get("/admin/profile-sources/preview")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["profiles"]) == 1
    p = data["profiles"][0]
    assert p["filename"] == "python-dev.yaml"
    assert p["name"] == "Python Dev"
    assert p["description"] == "Profil Python"
    assert p["extension_count"] == 8
    assert p["source_url"] == "https://example.com/profiles/python-dev.yaml"


def test_import_profile_from_source(tmp_path: Path) -> None:
    """POST /admin/profile-sources/import crée un profil partagé."""
    import yaml as _yaml

    profile_yaml = _yaml.dump({
        "name": "Python Dev",
        "description": "Profil Python",
        "extensions": ["ms-python.python"],
        "settings": {},
    })

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = profile_yaml

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    app = _make_admin_app(tmp_path)
    with TestClient(app) as client:
        with patch("portal.routes.profile_sources._check_ssrf", return_value=None):
            with patch("portal.routes.profile_sources.httpx.AsyncClient", return_value=mock_client):
                resp = client.post(
                    "/admin/profile-sources/import",
                    json={"source_url": "https://example.com/profiles/python-dev.yaml"},
                )

    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Python Dev"
    assert data["scope"] == "shared"
    assert data["slug"] == "python-dev"
    assert (tmp_path / "profiles" / "python-dev.yaml").is_file()


def test_import_profile_conflict(tmp_path: Path) -> None:
    """POST import retourne 409 si le slug existe déjà."""
    import yaml as _yaml

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(parents=True)
    (profiles_dir / "python-dev.yaml").write_text(
        _yaml.dump({"name": "Python Dev", "description": "", "extensions": [], "settings": {}}),
        encoding="utf-8",
    )

    profile_yaml = _yaml.dump({
        "name": "Python Dev",
        "description": "Autre profil",
        "extensions": [],
        "settings": {},
    })

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = profile_yaml

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    app = _make_admin_app(tmp_path)
    with TestClient(app) as client:
        with patch("portal.routes.profile_sources._check_ssrf", return_value=None):
            with patch("portal.routes.profile_sources.httpx.AsyncClient", return_value=mock_client):
                resp = client.post(
                    "/admin/profile-sources/import",
                    json={"source_url": "https://example.com/profiles/python-dev.yaml"},
                )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "profile_slug_conflict"
```

### Étape 2 : Vérifier que les tests échouent

```bash
cd backend && uv run pytest tests/routes/test_profile_sources.py -v
```

Résultat attendu : `ImportError` — module inexistant.

### Étape 3 : Implémenter `profile_sources.py`

Créer `backend/src/portal/routes/profile_sources.py` :

```python
from __future__ import annotations

import asyncio
import contextlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog
import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from ..auth.rbac import UserInfo, require_admin
from ..config.store import _data_root
from ..profiles.models import ProfileBody
from ..profiles.repository import ProfileError, ProfileRepository, slugify
from .recipe_sources import _check_ssrf

_log = structlog.get_logger(__name__)

router_admin = APIRouter(tags=["profile-sources"])

_YAML_FNAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.yaml$")


class ProfileSourcesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: list[str]


class ProfileImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_url: str


def _sources_path() -> Path:
    return _data_root() / "profile-sources.yaml"


def _load_sources() -> list[str]:
    path = _sources_path()
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("sources", []))


def _save_sources(sources: list[str]) -> None:
    path = _sources_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(yaml.dump({"sources": sources}, default_flow_style=False))
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _parse_toc_line(line: str) -> dict[str, Any] | None:
    """Parse 'filename | name | description | extension_count'. None si invalide."""
    parts = [p.strip() for p in line.split("|")]
    if len(parts) != 4:
        return None
    filename, name, description, ext_count_str = parts
    if not _YAML_FNAME_RE.fullmatch(filename):
        return None
    try:
        extension_count = int(ext_count_str)
    except ValueError:
        extension_count = 0
    return {
        "filename": filename,
        "name": name,
        "description": description,
        "extension_count": extension_count,
    }


async def _fetch_text(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url, timeout=5.0, follow_redirects=False)
    resp.raise_for_status()
    return resp.text


async def _preview_one_source(
    client: httpx.AsyncClient, base_url: str
) -> list[dict[str, Any]]:
    toc_url = base_url.rstrip("/") + "/toc.txt"
    try:
        toc = await _fetch_text(client, toc_url)
    except Exception as exc:
        _log.warning("profile_source_fetch_failed", url=toc_url, error=str(exc))
        return []
    results: list[dict[str, Any]] = []
    for raw_line in toc.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parsed = _parse_toc_line(line)
        if parsed is None:
            _log.warning("profile_toc_invalid_line", line=line)
            continue
        results.append(
            {
                **parsed,
                "source_url": f"{base_url.rstrip('/')}/{parsed['filename']}",
                "source_base": base_url,
            }
        )
    return results


@router_admin.get("/profile-sources")
async def get_profile_sources(
    user: UserInfo = Depends(require_admin),
) -> dict[str, Any]:
    sources = await asyncio.to_thread(_load_sources)
    return {"sources": sources}


@router_admin.put("/profile-sources")
async def put_profile_sources(
    body: ProfileSourcesPayload,
    user: UserInfo = Depends(require_admin),
) -> dict[str, Any]:
    for url in body.sources:
        if not url.startswith("https://"):
            raise HTTPException(
                status_code=422, detail=f"URL must be HTTPS: {url!r}"
            )
        await asyncio.to_thread(_check_ssrf, url)
    await asyncio.to_thread(_save_sources, body.sources)
    _log.info("profile_sources_updated", count=len(body.sources), by=user.login)
    return {"sources": body.sources}


@router_admin.get("/profile-sources/preview")
async def preview_profile_sources(
    user: UserInfo = Depends(require_admin),
) -> dict[str, Any]:
    sources = await asyncio.to_thread(_load_sources)
    all_profiles: list[dict[str, Any]] = []
    async with httpx.AsyncClient() as http:
        for src_url in sources:
            profiles = await _preview_one_source(http, src_url)
            all_profiles.extend(profiles)
    return {"profiles": all_profiles}


@router_admin.post("/profile-sources/import", status_code=201)
async def import_profile_from_source(
    body: ProfileImportRequest,
    user: UserInfo = Depends(require_admin),
) -> dict[str, Any]:
    await asyncio.to_thread(_check_ssrf, body.source_url)

    async with httpx.AsyncClient() as http:
        try:
            content = await _fetch_text(http, body.source_url)
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"Cannot fetch profile: {exc}"
            ) from exc

    try:
        raw = yaml.safe_load(content) or {}
        profile_body = ProfileBody(**raw)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Invalid profile YAML: {exc}"
        ) from exc

    data_root = _data_root()
    slug = slugify(profile_body.name)
    shared_dir = data_root / "profiles"
    shared_dir.mkdir(parents=True, exist_ok=True)

    if (shared_dir / f"{slug}.yaml").exists():
        raise HTTPException(status_code=409, detail="profile_slug_conflict")

    repo = ProfileRepository(data_root)
    profile = await asyncio.to_thread(repo.create_shared, profile_body)
    _log.info("profile_imported", slug=profile.slug, source=body.source_url, by=user.login)
    return profile.model_dump()
```

### Étape 4 : Vérifier que les tests passent

```bash
cd backend && uv run pytest tests/routes/test_profile_sources.py -v
```

Résultat attendu : 6/6 PASSED.

### Étape 5 : Lint + mypy

```bash
cd backend && uv run ruff check src/portal/routes/profile_sources.py tests/routes/test_profile_sources.py
cd backend && uv run mypy src/
```

### Étape 6 : Commit

```bash
git add backend/src/portal/routes/profile_sources.py backend/tests/routes/test_profile_sources.py
git commit -m "feat(profile-sources): routes admin CRUD sources + preview + import"
```

---

## Task 2 : Câblage `app.py`

**Files:**
- Modify: `backend/src/portal/app.py`

### Étape 1 : Ajouter l'import et inclure le router

Dans `backend/src/portal/app.py`, ajouter après la ligne `from .routes.recipe_sources import router_admin as recipe_sources_admin_router` :

```python
from .routes.profile_sources import router_admin as profile_sources_admin_router
```

Dans `create_app()`, ajouter après la ligne `app.include_router(recipe_sources_admin_router, prefix="/admin")` :

```python
    app.include_router(profile_sources_admin_router, prefix="/admin")
```

### Étape 2 : Vérifier la suite complète backend

```bash
cd backend && uv run pytest -v 2>&1 | tail -15
cd backend && uv run mypy src/
```

Résultat attendu : tous PASSED, 0 erreur mypy.

### Étape 3 : Commit

```bash
git add backend/src/portal/app.py
git commit -m "feat(app): inclure router profile-sources"
```

---

## Task 3 : Frontend — `useProfileSources.ts`

**Files:**
- Create: `frontend/src/features/admin/useProfileSources.ts`

### Étape 1 : Créer le hook

Créer `frontend/src/features/admin/useProfileSources.ts` :

```typescript
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { apiFetchJson } from '@/shared/api/client'

export interface RemoteProfile {
  filename: string
  name: string
  description: string
  extension_count: number
  source_url: string
  source_base: string
}

export function useProfileSources() {
  const qc = useQueryClient()
  const { t } = useTranslation()

  const sourcesQuery = useQuery<{ sources: string[] }>({
    queryKey: ['admin', 'profile-sources'],
    queryFn: () => apiFetchJson<{ sources: string[] }>('/admin/profile-sources'),
    staleTime: 5 * 60 * 1000,
  })

  const updateSources = useMutation({
    mutationFn: (sources: string[]) =>
      apiFetchJson<{ sources: string[] }>('/admin/profile-sources', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sources }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'profile-sources'] }),
    onError: (err: Error) => toast.error(err.message),
  })

  const previewQuery = useQuery<{ profiles: RemoteProfile[] }>({
    queryKey: ['admin', 'profile-sources', 'preview'],
    queryFn: () =>
      apiFetchJson<{ profiles: RemoteProfile[] }>('/admin/profile-sources/preview'),
    staleTime: 2 * 60 * 1000,
  })

  const importProfile = useMutation({
    mutationFn: (source_url: string) =>
      apiFetchJson<{ slug: string; name: string }>('/admin/profile-sources/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_url }),
      }),
    onSuccess: (data) => {
      toast.success(t('admin.profileSources.imported', { name: data.name }))
      qc.invalidateQueries({ queryKey: ['profiles'] })
      qc.invalidateQueries({ queryKey: ['admin', 'profile-sources', 'preview'] })
    },
    onError: (err: Error) => toast.error(err.message),
  })

  return { sourcesQuery, updateSources, previewQuery, importProfile }
}
```

### Étape 2 : Vérifier TypeScript

```bash
cd frontend && npx tsc --noEmit
```

Résultat attendu : 0 erreur.

### Étape 3 : Commit

```bash
git add frontend/src/features/admin/useProfileSources.ts
git commit -m "feat(admin): useProfileSources — hooks React Query profile-sources"
```

---

## Task 4 : Frontend — `AdminProfileSources.tsx`

**Files:**
- Create: `frontend/src/features/admin/AdminProfileSources.tsx`

### Étape 1 : Créer la page

Créer `frontend/src/features/admin/AdminProfileSources.tsx` :

```tsx
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, Trash2, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { useProfileSources, type RemoteProfile } from './useProfileSources'

export default function AdminProfileSources() {
  const { t } = useTranslation()
  const { sourcesQuery, updateSources, previewQuery, importProfile } = useProfileSources()
  const { data: sourcesData } = sourcesQuery
  const {
    data: previewData,
    isFetching: isLoadingGallery,
    refetch: refetchGallery,
  } = previewQuery

  const [newSourceUrl, setNewSourceUrl] = useState('')

  const sources = sourcesData?.sources ?? []
  const galleryProfiles = previewData?.profiles ?? []

  function addSource() {
    const url = newSourceUrl.trim()
    if (!url) return
    updateSources.mutate([...sources, url])
    setNewSourceUrl('')
  }

  function removeSource(idx: number) {
    updateSources.mutate(sources.filter((_, i) => i !== idx))
  }

  return (
    <div className="flex flex-col gap-10">

      {/* ── Sources ─────────────────────────────────────────────────── */}
      <section>
        <h2 className="mb-3 text-lg font-semibold">
          {t('admin.profileSources.sources')}
        </h2>
        <div className="flex flex-col gap-2">
          {sources.map((url, idx) => (
            <div key={idx} className="flex items-center gap-2">
              <Input
                value={url}
                readOnly
                className="flex-1 font-mono text-xs opacity-80"
              />
              <Button
                size="icon"
                variant="ghost"
                onClick={() => removeSource(idx)}
                aria-label={t('admin.deleteSource')}
              >
                <Trash2 className="h-4 w-4 text-destructive" />
              </Button>
            </div>
          ))}
          <div className="flex items-center gap-2">
            <Input
              value={newSourceUrl}
              onChange={(e) => setNewSourceUrl(e.target.value)}
              placeholder="https://raw.githubusercontent.com/…/profiles/"
              className="flex-1 font-mono text-xs"
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  addSource()
                }
              }}
            />
            <Button
              size="sm"
              variant="outline"
              onClick={addSource}
              disabled={!newSourceUrl.trim() || updateSources.isPending}
            >
              <Plus className="h-4 w-4 mr-1" />
              {t('admin.addSource')}
            </Button>
          </div>
        </div>
      </section>

      {/* ── Galerie ─────────────────────────────────────────────────── */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">
            {t('admin.profileSources.gallery')}
          </h2>
          <Button
            size="sm"
            variant="outline"
            onClick={() => refetchGallery()}
            disabled={isLoadingGallery}
          >
            <RefreshCw
              className={`h-4 w-4 mr-1 ${isLoadingGallery ? 'animate-spin' : ''}`}
            />
            {t('admin.refreshGallery')}
          </Button>
        </div>
        {isLoadingGallery && (
          <p className="text-sm text-muted-foreground">…</p>
        )}
        {!isLoadingGallery && galleryProfiles.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {t('admin.profileSources.empty')}
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {galleryProfiles.map((p: RemoteProfile) => (
            <div key={p.source_url} className="rounded-lg border bg-card p-4">
              <div className="mb-1 flex items-start justify-between gap-2">
                <div>
                  <div className="font-medium">{p.name}</div>
                  <Badge variant="secondary" className="mt-1 text-xs">
                    {p.extension_count} ext.
                  </Badge>
                </div>
                <Button
                  size="sm"
                  onClick={() => importProfile.mutate(p.source_url)}
                  disabled={importProfile.isPending}
                >
                  {importProfile.isPending
                    ? t('admin.profileSources.importing')
                    : t('admin.profileSources.import')}
                </Button>
              </div>
              <div className="mt-2 text-sm text-muted-foreground">
                {p.description}
              </div>
              <div className="mt-2 truncate text-xs text-muted-foreground font-mono">
                {p.source_base}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
```

### Étape 2 : Vérifier TypeScript

```bash
cd frontend && npx tsc --noEmit
```

### Étape 3 : Commit

```bash
git add frontend/src/features/admin/AdminProfileSources.tsx
git commit -m "feat(admin): AdminProfileSources — page galerie sources de profils"
```

---

## Task 5 : Router + navigation + i18n + MSW handlers

**Files:**
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/shared/layouts/AppShell.tsx`
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`
- Modify: `frontend/src/test/handlers.ts`

### Étape 1 : Router — ajouter la route

Dans `frontend/src/router.tsx`, ajouter après la ligne `const AdminProfiles = lazy(...)` :

```tsx
const AdminProfileSources = lazy(() => import('@/features/admin/AdminProfileSources'))
```

Dans le tableau de routes, ajouter après la route `/admin/profiles` :

```tsx
      {
        path: '/admin/profile-sources',
        element: <AdminGuard><Wrap><AdminProfileSources /></Wrap></AdminGuard>,
      },
```

### Étape 2 : AppShell — ajouter le lien nav

Dans `frontend/src/shared/layouts/AppShell.tsx`, dans le bloc `{isAdmin && (...)}`, ajouter après `<DropdownMenuItem onClick={() => navigate('/admin/profiles')}>` :

```tsx
                  <DropdownMenuItem onClick={() => navigate('/admin/profile-sources')}>
                    {t('admin.profileSources.navLabel')}
                  </DropdownMenuItem>
```

### Étape 3 : i18n fr.json

Dans `frontend/src/i18n/fr.json`, dans le bloc `"admin"`, ajouter après `"sharedProfiles"` :

```json
    "profileSources": {
      "navLabel": "Sources de profils",
      "sources": "Sources configurées",
      "gallery": "Galerie de profils",
      "empty": "Aucun profil disponible. Ajoutez une source et actualisez.",
      "import": "Importer",
      "importing": "Import…",
      "imported": "Profil «{{name}}» importé"
    }
```

### Étape 4 : i18n en.json

Même endroit dans `frontend/src/i18n/en.json` :

```json
    "profileSources": {
      "navLabel": "Profile Sources",
      "sources": "Configured Sources",
      "gallery": "Profile Gallery",
      "empty": "No profiles available. Add a source and refresh.",
      "import": "Import",
      "importing": "Importing…",
      "imported": "Profile «{{name}}» imported"
    }
```

### Étape 5 : MSW handlers

Dans `frontend/src/test/handlers.ts`, ajouter dans le tableau `handlers` :

```typescript
  http.get('/admin/profile-sources', () =>
    HttpResponse.json({ sources: [] })
  ),
  http.get('/admin/profile-sources/preview', () =>
    HttpResponse.json({ profiles: [] })
  ),
  http.put('/admin/profile-sources', async ({ request }) => {
    const body = await request.json() as { sources: string[] }
    return HttpResponse.json({ sources: body.sources })
  }),
  http.post('/admin/profile-sources/import', () =>
    HttpResponse.json(
      { slug: 'python-dev', name: 'Python Dev', scope: 'shared', description: '', extensions: [], settings: {} },
      { status: 201 }
    )
  ),
```

### Étape 6 : Vérifier TypeScript

```bash
cd frontend && npx tsc --noEmit
```

### Étape 7 : Commit

```bash
git add frontend/src/router.tsx frontend/src/shared/layouts/AppShell.tsx \
        frontend/src/i18n/fr.json frontend/src/i18n/en.json \
        frontend/src/test/handlers.ts
git commit -m "feat(admin): route /admin/profile-sources, nav, i18n, handlers MSW"
```

---

## Task 6 : Tests frontend `AdminProfileSources`

**Files:**
- Create: `frontend/src/features/admin/AdminProfileSources.test.tsx`

### Étape 1 : Créer le fichier de test

Créer `frontend/src/features/admin/AdminProfileSources.test.tsx` :

```tsx
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, beforeEach } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import AdminProfileSources from './AdminProfileSources'

describe('AdminProfileSources', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev', 'admin'] } })
  })

  it('affiche le titre de la section sources', () => {
    renderWithProviders(<AdminProfileSources />)
    expect(
      screen.getByRole('heading', { name: /sources configurées|configured sources/i })
    ).toBeInTheDocument()
  })

  it('affiche le titre de la galerie', () => {
    renderWithProviders(<AdminProfileSources />)
    expect(
      screen.getByRole('heading', { name: /galerie de profils|profile gallery/i })
    ).toBeInTheDocument()
  })

  it('permet d'ajouter une source via le champ texte', async () => {
    const { server } = await import('@/test/server')
    const { http, HttpResponse } = await import('msw')

    const captured: unknown[] = []
    server.use(
      http.put('/admin/profile-sources', async ({ request }) => {
        const body = await request.json()
        captured.push(body)
        return HttpResponse.json(body)
      })
    )

    renderWithProviders(<AdminProfileSources />)
    const input = screen.getByPlaceholderText(/https:\/\/raw\.githubusercontent\.com/i)
    await userEvent.type(input, 'https://example.com/profiles/')
    await userEvent.click(screen.getByRole('button', { name: /ajouter|add/i }))

    expect(captured).toHaveLength(1)
    expect((captured[0] as { sources: string[] }).sources).toContain(
      'https://example.com/profiles/'
    )
  })

  it('affiche le message vide quand la galerie est vide', async () => {
    renderWithProviders(<AdminProfileSources />)
    expect(
      await screen.findByText(/aucun profil disponible|no profiles available/i)
    ).toBeInTheDocument()
  })
})
```

### Étape 2 : Lancer les tests

```bash
cd frontend && npx vitest run src/features/admin/AdminProfileSources.test.tsx
```

Résultat attendu : 4/4 PASSED.

### Étape 3 : Suite complète frontend

```bash
cd frontend && npx vitest run 2>&1 | tail -15
cd frontend && npx tsc --noEmit
```

### Étape 4 : Suite complète backend

```bash
cd backend && uv run pytest -v 2>&1 | tail -15
```

### Étape 5 : Commit

```bash
git add frontend/src/features/admin/AdminProfileSources.test.tsx
git commit -m "test(admin): AdminProfileSources — sections, ajout source, galerie vide"
```
