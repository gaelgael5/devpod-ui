# Galerie de templates Jinja2 (import + export) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre de stocker les templates Jinja2 hors instance via une galerie (dépôt git) : import depuis des sources distantes et export ZIP round-trip, intégrés à la vue Admin Jinja-templates.

**Architecture:** Miroir de la Profile Gallery. Nouvelle table `jinja_template_sources` (sources toc.txt). Un module backend `routes/jinja_template_sources.py` (sources/preview/import) + un endpoint export dans `routes/jinja_templates.py`. Les templates atterrissent dans la table existante `jinja2_template` via `messages.db.upsert_template`. Frontend : hook `useJinjaTemplateSources` + section Galerie dans `AdminJinjaTemplates.tsx`.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy async / Alembic / pydantic v2 / pytest ; React 18 / TypeScript / TanStack Query / Vitest / MSW.

## Global Constraints

- Python : `from __future__ import annotations` en tête, async partout, `structlog` (jamais `print`), pydantic `extra="forbid"`, fichiers < 300 lignes.
- Aucune source non-HTTPS ; anti-SSRF (`_check_ssrf`) sur PUT sources / preview / import ; `follow_redirects=False` ; timeout 5 s.
- Tests : pytest-asyncio `asyncio_mode = "auto"` (pas de marqueur nécessaire). Frontend : Vitest + RTL, `describe`/`it`.
- Migrations Alembic : tête actuelle = `040`. Nouvelle révision = `041`, `down_revision = "040"`.
- Défaut source jinja : `https://raw.githubusercontent.com/ag-flow/ressources/refs/heads/main/jinja/toc.txt`.
- Convention toc jinja : `filename | key | culture | description`, fichiers `<key>.<culture>.j2` (body brut).
- Regex : filename `^[a-zA-Z0-9._-]+\.j2$`, key `^[a-zA-Z0-9_-]+$`, culture `^[a-z]{2}$`.
- Branche : `dev` uniquement. Commits en français conventionnel.
- Environnement local Windows : les tests qui montent l'app (`create_app`) échouent sur `fcntl` (Unix-only) et ceux qui touchent la DB skippent (pas de conteneur). Ils valident sur CI/serveur. Les tests **purs** (fonctions sans app/DB) tournent en local.

---

### Task 1: Table `jinja_template_sources` + migration 041 + accès DB

**Files:**
- Modify: `backend/src/portal/db/tables.py` (après le bloc `compose_catalog_sources`)
- Create: `backend/alembic/versions/041_jinja_template_sources.py`
- Modify: `backend/src/portal/db/sources.py`
- Test: `backend/tests/db/test_sources.py`

**Interfaces:**
- Produces: `jinja_template_sources` (Table) ; `load_jinja_template_sources(conn) -> list[str]` ; `save_jinja_template_sources(sources: list[str], conn) -> None` ; `_DEFAULT_JINJA_SOURCE: str`.

- [ ] **Step 1: Ajouter la table dans `tables.py`**

Insérer après la définition de `compose_catalog_sources` :

```python
jinja_template_sources = Table(
    "jinja_template_sources",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("url", Text, nullable=False, unique=True),
    Column("position", Integer, nullable=False, server_default="0"),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
```

- [ ] **Step 2: Créer la migration `041_jinja_template_sources.py`**

```python
"""jinja_template_sources : sources toc.txt pour la galerie de templates Jinja2.

Revision ID: 041
Revises: 040
Create Date: 2026-07-01
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "041"
down_revision: str | None = "040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jinja_template_sources",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("url", name="uq_jinja_template_sources_url"),
    )


def downgrade() -> None:
    op.drop_table("jinja_template_sources")
```

- [ ] **Step 3: Ajouter les accès DB dans `sources.py`**

Ajouter l'import de la table en tête (`from .tables import ... jinja_template_sources`) et, à la fin du fichier :

```python
_DEFAULT_JINJA_SOURCE = (
    "https://raw.githubusercontent.com/ag-flow/ressources/refs/heads/main/jinja/toc.txt"
)


async def load_jinja_template_sources(conn: AsyncConnection) -> list[str]:
    rows = (
        await conn.execute(
            select(jinja_template_sources.c.url)
            .where(jinja_template_sources.c.enabled.is_(True))
            .order_by(jinja_template_sources.c.position)
        )
    ).scalars().all()
    return list(rows) if rows else [_DEFAULT_JINJA_SOURCE]


async def save_jinja_template_sources(sources: list[str], conn: AsyncConnection) -> None:
    await conn.execute(delete(jinja_template_sources))
    if sources:
        await conn.execute(
            insert(jinja_template_sources),
            [{"url": url, "position": i} for i, url in enumerate(sources)],
        )
```

Mettre à jour la ligne d'import existante `from .tables import compose_catalog_sources, profile_sources, recipe_sources` pour inclure `jinja_template_sources` (ordre alphabétique).

- [ ] **Step 4: Écrire le test DB (défaut + roundtrip)**

Dans `backend/tests/db/test_sources.py`, ajouter les imports `_DEFAULT_JINJA_SOURCE, load_jinja_template_sources, save_jinja_template_sources` et :

```python
async def test_jinja_sources_default_when_empty(conn) -> None:
    result = await load_jinja_template_sources(conn)
    assert result == [_DEFAULT_JINJA_SOURCE]


async def test_jinja_sources_save_and_load(conn) -> None:
    urls = ["https://example.com/jinja/toc.txt", "https://example.org/j/"]
    await save_jinja_template_sources(urls, conn)
    result = await load_jinja_template_sources(conn)
    assert result == urls
```

(Réutiliser la fixture `conn` déjà utilisée par les tests recipe/profile de ce fichier.)

- [ ] **Step 5: Vérifier lint + mypy**

Run:
```bash
cd backend && uv run ruff check src/portal/db/sources.py src/portal/db/tables.py alembic/versions/041_jinja_template_sources.py && uv run mypy src/portal/db/sources.py
```
Expected: `All checks passed!` + `Success: no issues found`.

- [ ] **Step 6: Lancer les tests DB**

Run: `cd backend && uv run pytest tests/db/test_sources.py -q`
Expected: PASS sur CI/serveur ; **skip** en local (pas de conteneur DB). En local, vérifier au moins qu'aucune erreur de collecte n'apparaît.

- [ ] **Step 7: Commit**

```bash
git add backend/src/portal/db/tables.py backend/alembic/versions/041_jinja_template_sources.py backend/src/portal/db/sources.py backend/tests/db/test_sources.py
git commit -m "feat(jinja-gallery): table jinja_template_sources + migration 041 + accès DB"
```

---

### Task 2: Helper partagé `split_toc_url`

**Files:**
- Create: `backend/src/portal/routes/_sources_util.py`
- Test: `backend/tests/routes/test_sources_util.py`

**Interfaces:**
- Produces: `split_toc_url(source: str) -> tuple[str, str]` — retourne `(toc_url, dir_base)`. Accepte la forme dossier (`.../jinja/` ou `.../jinja`) comme l'URL complète (`.../jinja/toc.txt`). `dir_base` sans slash final ; `toc_url` pointe toujours sur un unique `toc.txt`.

- [ ] **Step 1: Écrire le test (rouge)**

`backend/tests/routes/test_sources_util.py` :

```python
from __future__ import annotations

import pytest

from portal.routes._sources_util import split_toc_url


@pytest.mark.parametrize(
    "source, expected",
    [
        ("https://ex.com/jinja/", ("https://ex.com/jinja/toc.txt", "https://ex.com/jinja")),
        ("https://ex.com/jinja", ("https://ex.com/jinja/toc.txt", "https://ex.com/jinja")),
        ("https://ex.com/jinja/toc.txt", ("https://ex.com/jinja/toc.txt", "https://ex.com/jinja")),
    ],
)
def test_split_toc_url(source: str, expected: tuple[str, str]) -> None:
    assert split_toc_url(source) == expected
```

- [ ] **Step 2: Lancer le test (échec attendu)**

Run: `cd backend && uv run pytest tests/routes/test_sources_util.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'portal.routes._sources_util'`.

- [ ] **Step 3: Implémenter le helper**

`backend/src/portal/routes/_sources_util.py` :

```python
"""Utilitaires partagés pour les galeries à base de toc.txt."""
from __future__ import annotations


def split_toc_url(source: str) -> tuple[str, str]:
    """Normalise une source en (toc_url, dir_base).

    Accepte indifféremment le dossier (``.../jinja/``) ou l'URL complète du
    fichier d'index (``.../jinja/toc.txt``). ``dir_base`` est le répertoire sans
    slash final ; ``toc_url`` pointe toujours sur un unique ``toc.txt``.
    """
    stripped = source.rstrip("/")
    head, _, tail = stripped.rpartition("/")
    if tail == "toc.txt":
        return stripped, head
    return f"{stripped}/toc.txt", stripped
```

- [ ] **Step 4: Lancer le test (vert)**

Run: `cd backend && uv run pytest tests/routes/test_sources_util.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Lint + mypy**

Run: `cd backend && uv run ruff check src/portal/routes/_sources_util.py tests/routes/test_sources_util.py && uv run mypy src/portal/routes/_sources_util.py`
Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add backend/src/portal/routes/_sources_util.py backend/tests/routes/test_sources_util.py
git commit -m "feat(jinja-gallery): helper partagé split_toc_url (dossier ou toc.txt)"
```

---

### Task 3: Module galerie backend — sources GET/PUT + preview

**Files:**
- Create: `backend/src/portal/routes/jinja_template_sources.py`
- Modify: `backend/src/portal/app.py` (import + `include_router`)
- Test: `backend/tests/routes/test_jinja_template_sources.py`

**Interfaces:**
- Consumes: `split_toc_url` (Task 2) ; `_check_ssrf` (de `recipe_sources`) ; `load_jinja_template_sources`, `save_jinja_template_sources` (Task 1) ; `messages.db` (`mdb`).
- Produces: `router_admin` (APIRouter) ; `_parse_toc_line(line) -> dict | None` ; `_preview_one_source(client, source) -> list[dict]` ; constantes regex `_J2_FNAME_RE`, `_KEY_RE`, `_CULTURE_RE` ; `_DEFAULT_SOURCE`.
- Routes : `GET /jinja-template-sources`, `PUT /jinja-template-sources`, `GET /jinja-template-sources/preview` (montées sous `/admin`).

- [ ] **Step 1: Écrire le test pur de preview (rouge)**

`backend/tests/routes/test_jinja_template_sources.py` :

```python
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class _RecordingClient:
    """Faux httpx.AsyncClient qui enregistre les URLs et sert le toc.txt."""

    def __init__(self, toc_text: str) -> None:
        self.toc_text = toc_text
        self.requested: list[str] = []

    async def get(self, url: str, timeout: float = 5.0, follow_redirects: bool = False):
        self.requested.append(url)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.text = self.toc_text
        return resp


@pytest.mark.parametrize(
    "source",
    ["https://ex.com/jinja/", "https://ex.com/jinja", "https://ex.com/jinja/toc.txt"],
)
async def test_preview_one_source_parses_and_builds_urls(source: str) -> None:
    from portal.routes.jinja_template_sources import _preview_one_source

    toc = (
        "test_host_available.fr.j2 | test_host_available | fr | Message dispo\n"
        "ligne invalide sans pipes\n"
        "bad.j2 | BAD KEY | fr | desc\n"  # key invalide -> skip
    )
    client = _RecordingClient(toc)
    results = await _preview_one_source(client, source)

    assert client.requested == ["https://ex.com/jinja/toc.txt"]
    assert len(results) == 1
    r = results[0]
    assert r["key"] == "test_host_available"
    assert r["culture"] == "fr"
    assert r["description"] == "Message dispo"
    assert r["source_url"] == "https://ex.com/jinja/test_host_available.fr.j2"
    assert r["source_base"] == "https://ex.com/jinja"
```

- [ ] **Step 2: Lancer (échec attendu)**

Run: `cd backend && uv run pytest tests/routes/test_jinja_template_sources.py -q`
Expected: FAIL — module inexistant.

- [ ] **Step 3: Implémenter le module (sources + preview)**

`backend/src/portal/routes/jinja_template_sources.py` :

```python
"""Routes admin : galerie de templates Jinja2 (sources toc.txt, preview, import)."""
from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..db.engine import get_conn
from ..db.sources import load_jinja_template_sources, save_jinja_template_sources
from ..messages import db as mdb
from ..messages.models import Jinja2Template
from ._sources_util import split_toc_url
from .recipe_sources import _check_ssrf

_log = structlog.get_logger(__name__)

router_admin = APIRouter(tags=["jinja-template-sources"])

_J2_FNAME_RE = re.compile(r"^[a-zA-Z0-9._-]+\.j2$")
_KEY_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_CULTURE_RE = re.compile(r"^[a-z]{2}$")

_DEFAULT_SOURCE = (
    "https://raw.githubusercontent.com/ag-flow/ressources/refs/heads/main/jinja/toc.txt"
)


class JinjaSourcesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: list[str]


class JinjaImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_url: str
    key: str
    culture: str
    overwrite: bool = False


def _parse_toc_line(line: str) -> dict[str, Any] | None:
    parts = [p.strip() for p in line.split("|")]
    if len(parts) != 4:
        return None
    filename, key, culture, description = parts
    if not _J2_FNAME_RE.fullmatch(filename):
        return None
    if not _KEY_RE.fullmatch(key):
        return None
    if not _CULTURE_RE.fullmatch(culture):
        return None
    return {"filename": filename, "key": key, "culture": culture, "description": description}


async def _fetch_text(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url, timeout=5.0, follow_redirects=False)
    resp.raise_for_status()
    return resp.text


async def _preview_one_source(client: httpx.AsyncClient, source: str) -> list[dict[str, Any]]:
    toc_url, dir_base = split_toc_url(source)
    try:
        toc = await _fetch_text(client, toc_url)
    except Exception as exc:
        _log.warning("jinja_source_fetch_failed", url=toc_url, error=str(exc))
        return []
    results: list[dict[str, Any]] = []
    for raw_line in toc.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parsed = _parse_toc_line(line)
        if parsed is None:
            _log.warning("jinja_toc_invalid_line", line=line)
            continue
        results.append(
            {
                **parsed,
                "source_url": f"{dir_base}/{parsed['filename']}",
                "source_base": dir_base,
            }
        )
    return results


@router_admin.get("/jinja-template-sources")
async def get_jinja_template_sources(
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    sources = await load_jinja_template_sources(conn)
    return {"sources": sources}


@router_admin.put("/jinja-template-sources")
async def put_jinja_template_sources(
    body: JinjaSourcesPayload,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    for url in body.sources:
        if not url.startswith("https://"):
            raise HTTPException(status_code=422, detail=f"URL must be HTTPS: {url!r}")
        await asyncio.to_thread(_check_ssrf, url)
    await save_jinja_template_sources(body.sources, conn)
    _log.info("jinja_sources_updated", count=len(body.sources), by=user.login)
    return {"sources": body.sources}


@router_admin.get("/jinja-template-sources/preview")
async def preview_jinja_template_sources(
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    sources = await load_jinja_template_sources(conn)
    all_templates: list[dict[str, Any]] = []
    async with httpx.AsyncClient() as http:
        for src_url in sources:
            try:
                await asyncio.to_thread(_check_ssrf, src_url)
            except HTTPException as exc:
                _log.warning("jinja_source_ssrf_blocked", url=src_url, detail=exc.detail)
                continue
            all_templates.extend(await _preview_one_source(http, src_url))
    return {"templates": all_templates}
```

(L'endpoint import sera ajouté en Task 4 dans ce même fichier.)

- [ ] **Step 4: Lancer le test pur (vert)**

Run: `cd backend && uv run pytest tests/routes/test_jinja_template_sources.py::test_preview_one_source_parses_and_builds_urls -q`
Expected: `3 passed`.

- [ ] **Step 5: Monter le router dans `app.py`**

Ajouter près des autres imports de routes :
```python
from .routes.jinja_template_sources import router_admin as jinja_sources_admin_router
```
Et près de `app.include_router(jinja_templates_router, prefix="/admin")` :
```python
app.include_router(jinja_sources_admin_router, prefix="/admin")
```

- [ ] **Step 6: Lint + mypy**

Run: `cd backend && uv run ruff check src/portal/routes/jinja_template_sources.py tests/routes/test_jinja_template_sources.py && uv run mypy src/portal/routes/jinja_template_sources.py`
Expected: OK.

- [ ] **Step 7: Commit**

```bash
git add backend/src/portal/routes/jinja_template_sources.py backend/tests/routes/test_jinja_template_sources.py backend/src/portal/app.py
git commit -m "feat(jinja-gallery): sources + preview de la galerie Jinja2 (backend)"
```

---

### Task 4: Endpoint import (avec conflit 409)

**Files:**
- Modify: `backend/src/portal/routes/jinja_template_sources.py` (ajout endpoint import)
- Test: `backend/tests/routes/test_jinja_template_sources.py` (tests import — app/DB)

**Interfaces:**
- Consumes: `JinjaImportRequest`, `_check_ssrf`, `_fetch_text`, `mdb.get_template`, `mdb.upsert_template`, `Jinja2Template`.
- Produces: `POST /jinja-template-sources/import` → renvoie le `Jinja2Template` importé ; 409 `template_exists` si présent sans `overwrite`.

- [ ] **Step 1: Écrire les tests import (app/DB)**

Ajouter à `test_jinja_template_sources.py` un builder d'app admin (calqué sur `test_profile_sources.py`) et trois tests. Réutiliser le helper `_make_admin_app` : le copier depuis `tests/routes/test_profile_sources.py` (mêmes imports `portal.settings`, `require_admin` override). Puis :

```python
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


def _mock_http(body_text: str):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.text = body_text
    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def test_import_creates_template(tmp_path: Path) -> None:
    app = _make_admin_app(tmp_path)
    http = _mock_http("Bonjour {{ user.login }}")
    with (
        TestClient(app) as client,
        patch("portal.routes.jinja_template_sources._check_ssrf", return_value=None),
        patch("portal.routes.jinja_template_sources.httpx.AsyncClient", return_value=http),
    ):
        resp = client.post(
            "/admin/jinja-template-sources/import",
            json={
                "source_url": "https://ex.com/jinja/welcome.fr.j2",
                "key": "welcome",
                "culture": "fr",
            },
        )
    assert resp.status_code == 200
    assert resp.json()["key"] == "welcome"
    assert resp.json()["body"] == "Bonjour {{ user.login }}"


def test_import_conflict_without_overwrite(tmp_path: Path) -> None:
    app = _make_admin_app(tmp_path)
    http = _mock_http("v1")
    common = dict(
        source_url="https://ex.com/jinja/welcome.fr.j2", key="welcome", culture="fr"
    )
    with (
        TestClient(app) as client,
        patch("portal.routes.jinja_template_sources._check_ssrf", return_value=None),
        patch("portal.routes.jinja_template_sources.httpx.AsyncClient", return_value=http),
    ):
        first = client.post("/admin/jinja-template-sources/import", json=common)
        assert first.status_code == 200
        second = client.post("/admin/jinja-template-sources/import", json=common)
    assert second.status_code == 409
    assert second.json()["detail"] == "template_exists"


def test_import_overwrite(tmp_path: Path) -> None:
    app = _make_admin_app(tmp_path)
    with (
        TestClient(app) as client,
        patch("portal.routes.jinja_template_sources._check_ssrf", return_value=None),
    ):
        with patch(
            "portal.routes.jinja_template_sources.httpx.AsyncClient",
            return_value=_mock_http("v1"),
        ):
            client.post(
                "/admin/jinja-template-sources/import",
                json={"source_url": "https://ex.com/jinja/welcome.fr.j2",
                      "key": "welcome", "culture": "fr"},
            )
        with patch(
            "portal.routes.jinja_template_sources.httpx.AsyncClient",
            return_value=_mock_http("v2"),
        ):
            resp = client.post(
                "/admin/jinja-template-sources/import",
                json={"source_url": "https://ex.com/jinja/welcome.fr.j2",
                      "key": "welcome", "culture": "fr", "overwrite": True},
            )
    assert resp.status_code == 200
    assert resp.json()["body"] == "v2"
```

- [ ] **Step 2: Lancer (échec attendu)**

Run: `cd backend && uv run pytest tests/routes/test_jinja_template_sources.py -k import -q`
Expected sur CI : FAIL (endpoint 404). En local : les tests skippent/échouent au montage app (`fcntl`) — passer à l'implémentation.

- [ ] **Step 3: Implémenter l'endpoint import**

Ajouter à la fin de `jinja_template_sources.py` :

```python
@router_admin.post("/jinja-template-sources/import", status_code=200)
async def import_jinja_template(
    body: JinjaImportRequest,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> Jinja2Template:
    if not _KEY_RE.fullmatch(body.key):
        raise HTTPException(status_code=422, detail=f"Invalid key: {body.key!r}")
    if not _CULTURE_RE.fullmatch(body.culture):
        raise HTTPException(status_code=422, detail=f"Invalid culture: {body.culture!r}")
    filename = body.source_url.rsplit("/", 1)[-1]
    if not _J2_FNAME_RE.fullmatch(filename):
        raise HTTPException(status_code=422, detail=f"Invalid filename: {filename!r}")

    await asyncio.to_thread(_check_ssrf, body.source_url)
    async with httpx.AsyncClient() as http:
        try:
            content = await _fetch_text(http, body.source_url)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Cannot fetch template: {exc}") from exc

    existing = await mdb.get_template(conn, body.key, body.culture)
    if existing is not None and not body.overwrite:
        raise HTTPException(status_code=409, detail="template_exists")

    tpl = Jinja2Template(key=body.key, culture=body.culture, body=content)
    await mdb.upsert_template(conn, tpl)
    _log.info(
        "jinja_template_imported",
        key=body.key,
        culture=body.culture,
        overwrite=body.overwrite,
        by=user.login,
    )
    return tpl
```

- [ ] **Step 4: Lancer les tests import**

Run: `cd backend && uv run pytest tests/routes/test_jinja_template_sources.py -k import -q`
Expected: PASS sur CI/serveur (skip/`fcntl` en local).

- [ ] **Step 5: Lint + mypy**

Run: `cd backend && uv run ruff check src/portal/routes/jinja_template_sources.py tests/routes/test_jinja_template_sources.py && uv run mypy src/portal/routes/jinja_template_sources.py`
Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add backend/src/portal/routes/jinja_template_sources.py backend/tests/routes/test_jinja_template_sources.py
git commit -m "feat(jinja-gallery): import de template avec conflit 409 (informer avant écrasement)"
```

---

### Task 5: Endpoint export ZIP

**Files:**
- Modify: `backend/src/portal/routes/jinja_templates.py` (helper `build_templates_zip` + route `/jinja-templates/export`)
- Test: `backend/tests/routes/test_jinja_export.py`

**Interfaces:**
- Produces: `build_templates_zip(templates: list[Jinja2Template]) -> bytes` (pur) ; `GET /jinja-templates/export` → `application/zip`.

- [ ] **Step 1: Écrire le test pur du builder ZIP (rouge)**

`backend/tests/routes/test_jinja_export.py` :

```python
from __future__ import annotations

import io
import zipfile

from portal.messages.models import Jinja2Template
from portal.routes.jinja_templates import build_templates_zip


def test_build_templates_zip_roundtrip() -> None:
    templates = [
        Jinja2Template(key="welcome", culture="fr", body="Bonjour | salut\nligne2"),
        Jinja2Template(key="welcome", culture="en", body="Hi there"),
    ]
    data = build_templates_zip(templates)
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = set(zf.namelist())
    assert names == {"toc.txt", "welcome.fr.j2", "welcome.en.j2"}
    # bodies préservés à l'identique
    assert zf.read("welcome.fr.j2").decode() == "Bonjour | salut\nligne2"
    assert zf.read("welcome.en.j2").decode() == "Hi there"
    # toc : 4 champs, description sanitizée (pas de pipe, pas de newline)
    toc = zf.read("toc.txt").decode().splitlines()
    assert "welcome.fr.j2 | welcome | fr | Bonjour / salut" in toc
    assert "welcome.en.j2 | welcome | en | Hi there" in toc


def test_build_templates_zip_empty() -> None:
    data = build_templates_zip([])
    zf = zipfile.ZipFile(io.BytesIO(data))
    assert zf.namelist() == ["toc.txt"]
    assert zf.read("toc.txt").decode() == ""
```

- [ ] **Step 2: Lancer (échec attendu)**

Run: `cd backend && uv run pytest tests/routes/test_jinja_export.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_templates_zip'`.

- [ ] **Step 3: Implémenter le builder + la route**

Dans `jinja_templates.py`, ajouter en tête les imports :
```python
import io
import zipfile

from fastapi import Response
```
Ajouter le helper (niveau module) :
```python
def _toc_desc(body: str) -> str:
    """Première ligne non vide, sans pipe ni saut de ligne, tronquée à 80 car."""
    for line in body.splitlines():
        s = line.strip()
        if s:
            return s.replace("|", "/")[:80]
    return ""


def build_templates_zip(templates: list[Jinja2Template]) -> bytes:
    """Construit un bundle ZIP : toc.txt + un <key>.<culture>.j2 par template."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        toc_lines: list[str] = []
        for t in templates:
            fname = f"{t.key}.{t.culture}.j2"
            toc_lines.append(f"{fname} | {t.key} | {t.culture} | {_toc_desc(t.body)}")
            zf.writestr(fname, t.body)
        toc = ("\n".join(toc_lines) + "\n") if toc_lines else ""
        zf.writestr("toc.txt", toc)
    return buf.getvalue()
```
Ajouter la route **avant** `get_jinja_template` (route `/{key}/{culture}`) :
```python
@router.get("/jinja-templates/export")
async def export_jinja_templates(
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> Response:
    templates = await mdb.list_templates(conn)
    data = build_templates_zip(templates)
    _log.info("jinja_templates_exported", count=len(templates), by=user.login)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="jinja-templates.zip"'},
    )
```

- [ ] **Step 4: Lancer le test pur (vert)**

Run: `cd backend && uv run pytest tests/routes/test_jinja_export.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Lint + mypy**

Run: `cd backend && uv run ruff check src/portal/routes/jinja_templates.py tests/routes/test_jinja_export.py && uv run mypy src/portal/routes/jinja_templates.py`
Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add backend/src/portal/routes/jinja_templates.py backend/tests/routes/test_jinja_export.py
git commit -m "feat(jinja-gallery): export ZIP des templates Jinja2 (round-trip)"
```

---

### Task 6: Frontend — hook `useJinjaTemplateSources`

**Files:**
- Create: `frontend/src/features/admin/useJinjaTemplateSources.ts`

**Interfaces:**
- Produces: `RemoteJinjaTemplate` (type) ; `useJinjaTemplateSources()` → `{ sourcesQuery, updateSources, previewQuery, importTemplate, exportBundle }`.
  - `importTemplate.mutate({ source_url, key, culture, overwrite })`
  - `exportBundle(): Promise<void>` (déclenche le téléchargement du zip)

- [ ] **Step 1: Implémenter le hook**

`frontend/src/features/admin/useJinjaTemplateSources.ts` :

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { apiFetch, apiFetchJson } from '@/shared/api/client'

export interface RemoteJinjaTemplate {
  filename: string
  key: string
  culture: string
  description: string
  source_url: string
  source_base: string
}

interface ImportArgs {
  source_url: string
  key: string
  culture: string
  overwrite: boolean
}

export function useJinjaTemplateSources() {
  const qc = useQueryClient()
  const { t } = useTranslation()

  const sourcesQuery = useQuery<{ sources: string[] }>({
    queryKey: ['admin', 'jinja-template-sources'],
    queryFn: () => apiFetchJson<{ sources: string[] }>('/admin/jinja-template-sources'),
    staleTime: 5 * 60 * 1000,
  })

  const updateSources = useMutation({
    mutationFn: (sources: string[]) =>
      apiFetchJson<{ sources: string[] }>('/admin/jinja-template-sources', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sources }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'jinja-template-sources'] }),
    onError: (err: Error) => toast.error(err.message),
  })

  const previewQuery = useQuery<{ templates: RemoteJinjaTemplate[] }>({
    queryKey: ['admin', 'jinja-template-sources', 'preview'],
    queryFn: () =>
      apiFetchJson<{ templates: RemoteJinjaTemplate[] }>('/admin/jinja-template-sources/preview'),
    staleTime: 2 * 60 * 1000,
  })

  const importTemplate = useMutation({
    mutationFn: (args: ImportArgs) =>
      apiFetchJson<{ key: string; culture: string }>('/admin/jinja-template-sources/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(args),
      }),
    onSuccess: (data) => {
      toast.success(t('jinjaTemplates.gallery.imported', { key: data.key, culture: data.culture }))
      qc.invalidateQueries({ queryKey: ['jinja-templates'] })
      qc.invalidateQueries({ queryKey: ['admin', 'jinja-template-sources', 'preview'] })
    },
    onError: (err: Error) => toast.error(err.message),
  })

  async function exportBundle(): Promise<void> {
    const res = await apiFetch('/admin/jinja-templates/export')
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'jinja-templates.zip'
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  return { sourcesQuery, updateSources, previewQuery, importTemplate, exportBundle }
}
```

- [ ] **Step 2: Vérifier le typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: aucune erreur sur ce fichier.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/admin/useJinjaTemplateSources.ts
git commit -m "feat(jinja-gallery): hook useJinjaTemplateSources (sources/preview/import/export)"
```

---

### Task 7: Frontend — section Galerie + bouton Export + i18n

**Files:**
- Modify: `frontend/src/features/admin/AdminJinjaTemplates.tsx`
- Modify: `frontend/src/i18n/fr.json`, `frontend/src/i18n/en.json`
- Create: `frontend/src/features/admin/AdminJinjaTemplatesGallery.test.tsx`

**Interfaces:**
- Consumes: `useJinjaTemplateSources` (Task 6), `useJinjaTemplates` (existant).

- [ ] **Step 1: Ajouter les clés i18n (fr)**

Dans `frontend/src/i18n/fr.json`, remplacer la dernière clé du bloc `jinjaTemplates` (`confirmDelete`) en conservant sa valeur et en ajoutant après elle :

```json
    "confirmDelete": "Supprimer le template {{key}} / {{culture}} ?",
    "export": "Exporter",
    "gallery": {
      "sources": "Sources configurées",
      "title": "Galerie de templates",
      "add": "Ajouter",
      "refresh": "Rafraîchir la galerie",
      "import": "Importer",
      "importing": "Import…",
      "present": "présent",
      "empty": "Aucun template disponible dans les sources.",
      "filter": "Filtrer…",
      "imported": "Template {{key}} / {{culture}} importé",
      "overwriteConfirmTitle": "Écraser le template existant ?",
      "overwriteConfirmDescription": "Le template {{key}} / {{culture}} existe déjà en base. L'importer écrasera son contenu actuel.",
      "overwrite": "Écraser"
    }
```

- [ ] **Step 2: Ajouter les clés i18n (en)**

Dans `frontend/src/i18n/en.json`, même emplacement :

```json
    "confirmDelete": "Delete template {{key}} / {{culture}}?",
    "export": "Export",
    "gallery": {
      "sources": "Configured sources",
      "title": "Template gallery",
      "add": "Add",
      "refresh": "Refresh gallery",
      "import": "Import",
      "importing": "Importing…",
      "present": "present",
      "empty": "No templates available in sources.",
      "filter": "Filter…",
      "imported": "Template {{key}} / {{culture}} imported",
      "overwriteConfirmTitle": "Overwrite existing template?",
      "overwriteConfirmDescription": "Template {{key}} / {{culture}} already exists. Importing will overwrite its current content.",
      "overwrite": "Overwrite"
    }
```

(Adapter la valeur `confirmDelete` en anglais si elle diffère déjà ; ne pas dupliquer la clé.)

- [ ] **Step 3: Ajouter la section Galerie + bouton Export dans la vue**

Dans `AdminJinjaTemplates.tsx` :

1. Imports en tête :
```tsx
import { Badge } from '@/components/ui/badge'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { useJinjaTemplateSources, type RemoteJinjaTemplate } from './useJinjaTemplateSources'
```

2. Dans le composant, après `const { templates, upsert, remove, preview } = useJinjaTemplates()` :
```tsx
  const { sourcesQuery, updateSources, previewQuery, importTemplate, exportBundle } =
    useJinjaTemplateSources()
  const [newSourceUrl, setNewSourceUrl] = useState('')
  const [confirmOverwrite, setConfirmOverwrite] = useState<RemoteJinjaTemplate | null>(null)

  const sources = sourcesQuery.data?.sources ?? []
  const remoteTemplates = previewQuery.data?.templates ?? []
  const presentKeys = new Set((templates.data ?? []).map(t => `${t.key}/${t.culture}`))

  function isPresent(rt: RemoteJinjaTemplate) {
    return presentKeys.has(`${rt.key}/${rt.culture}`)
  }
  function addSource() {
    const url = newSourceUrl.trim()
    if (!url) return
    updateSources.mutate([...sources, url])
    setNewSourceUrl('')
  }
  function removeSource(idx: number) {
    updateSources.mutate(sources.filter((_, i) => i !== idx))
  }
  function doImport(rt: RemoteJinjaTemplate, overwrite: boolean) {
    importTemplate.mutate(
      { source_url: rt.source_url, key: rt.key, culture: rt.culture, overwrite },
      { onSuccess: () => setConfirmOverwrite(null) },
    )
  }
  function onImportClick(rt: RemoteJinjaTemplate) {
    if (isPresent(rt)) setConfirmOverwrite(rt)
    else doImport(rt, false)
  }
```

3. Dans le header, à côté du bouton « Nouveau » :
```tsx
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => exportBundle()}>{t('jinjaTemplates.export')}</Button>
          <Button onClick={openNew}>{t('jinjaTemplates.new')}</Button>
        </div>
```
(remplace le `<Button onClick={openNew}>` isolé existant.)

4. À la fin du composant, juste avant la fermeture de la `<div>` racine, ajouter la section galerie + le dialog :
```tsx
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">{t('jinjaTemplates.gallery.sources')}</h2>
        <div className="flex flex-col gap-2">
          {sources.map((url, idx) => (
            <div key={idx} className="flex items-center gap-2">
              <Input value={url} readOnly className="flex-1 font-mono text-xs opacity-80" />
              <Button size="sm" variant="ghost" onClick={() => removeSource(idx)}>✕</Button>
            </div>
          ))}
          <div className="flex items-center gap-2">
            <Input
              value={newSourceUrl}
              onChange={e => setNewSourceUrl(e.target.value)}
              placeholder="https://raw.githubusercontent.com/…/jinja/toc.txt"
              className="flex-1 font-mono text-xs"
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addSource() } }}
            />
            <Button size="sm" variant="outline" onClick={addSource}
              disabled={!newSourceUrl.trim() || updateSources.isPending}>
              {t('jinjaTemplates.gallery.add')}
            </Button>
          </div>
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">{t('jinjaTemplates.gallery.title')}</h2>
          <Button size="sm" variant="outline" onClick={() => previewQuery.refetch()}
            disabled={previewQuery.isFetching}>
            {t('jinjaTemplates.gallery.refresh')}
          </Button>
        </div>
        {remoteTemplates.length === 0 && !previewQuery.isFetching && (
          <p className="text-sm text-muted-foreground">{t('jinjaTemplates.gallery.empty')}</p>
        )}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {remoteTemplates.map(rt => (
            <div key={rt.source_url} className="rounded-lg border bg-card p-4">
              <div className="mb-1 flex items-start justify-between gap-2">
                <div>
                  <div className="font-mono text-sm font-medium">{rt.key}</div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    <Badge variant="secondary" className="text-xs">{rt.culture}</Badge>
                    {isPresent(rt) && (
                      <Badge variant="outline" className="text-xs">{t('jinjaTemplates.gallery.present')}</Badge>
                    )}
                  </div>
                </div>
                <Button size="sm" onClick={() => onImportClick(rt)} disabled={importTemplate.isPending}>
                  {importTemplate.isPending
                    ? t('jinjaTemplates.gallery.importing')
                    : t('jinjaTemplates.gallery.import')}
                </Button>
              </div>
              <div className="mt-2 text-sm text-muted-foreground">{rt.description}</div>
            </div>
          ))}
        </div>
      </section>

      <Dialog open={Boolean(confirmOverwrite)} onOpenChange={o => !o && setConfirmOverwrite(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('jinjaTemplates.gallery.overwriteConfirmTitle')}</DialogTitle>
            <DialogDescription>
              {t('jinjaTemplates.gallery.overwriteConfirmDescription', {
                key: confirmOverwrite?.key, culture: confirmOverwrite?.culture,
              })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmOverwrite(null)}>{t('common.cancel')}</Button>
            <Button variant="destructive" disabled={importTemplate.isPending}
              onClick={() => confirmOverwrite && doImport(confirmOverwrite, true)}>
              {t('jinjaTemplates.gallery.overwrite')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
```

- [ ] **Step 4: Écrire le test composant**

`frontend/src/features/admin/AdminJinjaTemplatesGallery.test.tsx` (calqué sur `AdminProfileSources.test.tsx`) :

```tsx
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, beforeEach } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import AdminJinjaTemplates from './AdminJinjaTemplates'

describe('AdminJinjaTemplates — galerie', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev', 'admin'] } })
  })

  it('affiche le titre de la galerie', () => {
    renderWithProviders(<AdminJinjaTemplates />)
    expect(
      screen.getByRole('heading', { name: /galerie de templates|template gallery/i }),
    ).toBeInTheDocument()
  })

  it('affiche un bouton Exporter', () => {
    renderWithProviders(<AdminJinjaTemplates />)
    expect(screen.getByRole('button', { name: /exporter|export/i })).toBeInTheDocument()
  })

  it("ajoute une source via le champ texte", async () => {
    const { server } = await import('@/test/server')
    const { http, HttpResponse } = await import('msw')
    const captured: unknown[] = []
    server.use(
      http.put('/admin/jinja-template-sources', async ({ request }) => {
        const body = await request.json()
        captured.push(body)
        return HttpResponse.json(body)
      }),
    )
    renderWithProviders(<AdminJinjaTemplates />)
    const input = screen.getByPlaceholderText(/jinja\/toc\.txt/i)
    await userEvent.type(input, 'https://example.com/jinja/toc.txt')
    await userEvent.click(screen.getByRole('button', { name: /^ajouter$|^add$/i }))
    expect(captured).toHaveLength(1)
    expect((captured[0] as { sources: string[] }).sources).toContain(
      'https://example.com/jinja/toc.txt',
    )
  })
})
```

Ajouter les handlers MSW par défaut dans `frontend/src/test/handlers.ts` (GET `/admin/jinja-template-sources` → `{sources: []}`, GET `/admin/jinja-template-sources/preview` → `{templates: []}`, GET `/admin/jinja-templates` → `[]`) s'ils n'existent pas déjà, pour que les requêtes du hook résolvent en test.

- [ ] **Step 5: Lancer les tests frontend + typecheck**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/features/admin/AdminJinjaTemplatesGallery.test.tsx`
Expected: typecheck OK, `3 passed`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/admin/AdminJinjaTemplates.tsx frontend/src/i18n/fr.json frontend/src/i18n/en.json frontend/src/features/admin/AdminJinjaTemplatesGallery.test.tsx frontend/src/test/handlers.ts
git commit -m "feat(jinja-gallery): section galerie + export dans la vue Jinja-templates"
```

---

### Task 8: Vérification finale + déploiement de test

**Files:** aucun (vérification transverse).

- [ ] **Step 1: Backend — lint + mypy + tests exécutables localement**

Run:
```bash
cd backend && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/ \
  && uv run pytest tests/routes/test_sources_util.py tests/routes/test_jinja_template_sources.py::test_preview_one_source_parses_and_builds_urls tests/routes/test_jinja_export.py -q
```
Expected: lint/format/mypy OK ; tests purs `PASS`.

- [ ] **Step 2: Frontend — lint + typecheck + tests**

Run: `cd frontend && npm run lint && npx tsc --noEmit && npx vitest run src/features/admin`
Expected: OK.

- [ ] **Step 3: Déploiement de test (suivre `TESTER-MON-DEV.md`)**

Pousser `dev`, lancer `dev-deploy.sh` sur test1, appliquer la migration, puis vérifier via curl/Browserless :
- `GET /admin/jinja-template-sources` renvoie le défaut ;
- `GET /admin/jinja-template-sources/preview` liste les templates du dépôt ;
- import d'un template (nouveau → 200 ; ré-import → 409 sans overwrite) ;
- `GET /admin/jinja-templates/export` télécharge un zip valide ;
- round-trip : export → décompression → committer dans le dépôt → preview → import.

Lire les **vrais logs** (`log.info`/`log.warning` `jinja_*`). Ne pas simuler l'environnement en local.

- [ ] **Step 4: Commit éventuel de correctifs**

Si des écarts sont trouvés au déploiement, corriger, relancer lint/mypy/tests, committer (`fix(jinja-gallery): …`).

---

## Notes d'exécution

- **Ordre strict** : Task 1 → 8. Les tests app/DB (Task 1 step 6, Task 4) ne valident qu'en CI/serveur ; ne pas bloquer l'avancement local dessus, mais **ne pas les déclarer verts** sans preuve CI/serveur.
- Ne rien pousser sur git sans demande explicite de l'utilisateur (règle CLAUDE.md) — les `git commit` des tâches restent locaux jusqu'à autorisation de push.
- Le helper `split_toc_url` est volontairement partagé et pourra remplacer les implémentations locales de recipes/compose/profiles dans un chantier ultérieur (hors périmètre).
