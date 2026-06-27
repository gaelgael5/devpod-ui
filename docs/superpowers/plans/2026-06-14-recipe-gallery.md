# Recipe Gallery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Galerie de recettes avec sources distantes configurables, import admin, picker ordonné dans WorkspaceCreate, et vue logs dans WorkspaceCard.

**Architecture:** Les recettes de la galerie sont des fichiers `.sh` hébergés sur des URLs distantes, indexées par un `toc.txt` (un filename `.sh` par ligne). Les admins configurent les URLs de `toc.txt` depuis AdminRecipes. La page AdminRecipes est restructurée : gestionnaire de sources en haut, galerie distante au milieu (fetch live), recettes locales en bas. Le picker de recettes dans WorkspaceCreate devient un picker ordonné (liste numérotée, picker modal). Les logs de provisionnement sont consultables depuis WorkspaceCard via un dialog auto-refresh.

**Tech Stack:** Python 3.12 + FastAPI + httpx (fetch sources distantes) + React 18 + TypeScript strict + TanStack Query + shadcn/ui + i18next

---

## Structure des fichiers

### Fichiers créés
- `recipes/toc.txt` — index des recettes livrées par défaut
- `recipes/git.sh`, `recipes/node.sh`, `recipes/python.sh`, `recipes/docker.sh`
- `backend/src/portal/routes/recipe_sources.py` — endpoints CRUD sources + preview + import
- `backend/tests/recipe_sources/__init__.py`
- `backend/tests/recipe_sources/test_recipe_sources.py`
- `frontend/src/features/admin/useRecipeSources.ts`
- `frontend/src/features/workspaces/useWorkspaceLogs.ts`
- `frontend/src/features/workspaces/LogDialog.tsx`
- `frontend/src/features/recipes/OrderedRecipePicker.tsx`

### Fichiers modifiés
- `backend/src/portal/app.py` — enregistrement router recipe_sources
- `backend/src/portal/routes/workspace_ops.py` — ajout endpoint logs
- `frontend/src/features/admin/AdminRecipes.tsx` — redesign complet
- `frontend/src/features/workspaces/WorkspaceCreate.tsx` — picker ordonné
- `frontend/src/features/workspaces/WorkspaceCard.tsx` — bouton Logs
- `frontend/src/i18n/fr.json`, `en.json` — nouvelles clés

---

### Task 1 : Répertoire `recipes/` avec scripts bash + toc.txt

**Files:**
- Create: `recipes/toc.txt`
- Create: `recipes/git.sh`
- Create: `recipes/node.sh`
- Create: `recipes/python.sh`
- Create: `recipes/docker.sh`

Convention : chaque fichier `.sh` commence par des commentaires `# name:`, `# description:`, `# version:` (avant le shebang), sur les premières lignes du fichier.

- [ ] **Step 1 : Créer `recipes/git.sh`**

```bash
# name: Git
# description: Configure Git avec user.name et user.email via variables d'environnement
# version: 1.0.0
#!/usr/bin/env bash
set -e
echo "Configuring Git..."
git config --global user.name "${GIT_USER_NAME:-dev}"
git config --global user.email "${GIT_USER_EMAIL:-dev@example.com}"
echo "Git configured."
```

- [ ] **Step 2 : Créer `recipes/node.sh`**

```bash
# name: Node.js LTS
# description: Installe Node.js LTS via nvm dans le workspace
# version: 1.0.0
#!/usr/bin/env bash
set -e
echo "Installing Node.js LTS via nvm..."
export NVM_DIR="/usr/local/nvm"
mkdir -p "$NVM_DIR"
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
# shellcheck disable=SC1090
source "$NVM_DIR/nvm.sh"
nvm install --lts
nvm alias default node
echo "Node.js $(node --version) installed."
```

- [ ] **Step 3 : Créer `recipes/python.sh`**

```bash
# name: Python 3.12
# description: Installe Python 3.12 et pip via pyenv
# version: 1.0.0
#!/usr/bin/env bash
set -e
echo "Installing Python 3.12 via pyenv..."
export PYENV_ROOT="$HOME/.pyenv"
curl -fsSL https://pyenv.run | bash
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
pyenv install 3.12
pyenv global 3.12
pip install --upgrade pip
echo "Python $(python --version) installed."
```

- [ ] **Step 4 : Créer `recipes/docker.sh`**

```bash
# name: Docker CLI
# description: Installe le client Docker CLI (sans daemon)
# version: 1.0.0
#!/usr/bin/env bash
set -e
echo "Installing Docker CLI..."
apt-get update -qq
apt-get install -y --no-install-recommends docker-ce-cli
echo "Docker CLI $(docker --version) installed."
```

- [ ] **Step 5 : Créer `recipes/toc.txt`**

```
git.sh
node.sh
python.sh
docker.sh
```

- [ ] **Step 6 : Commit**

```bash
git add recipes/
git commit -m "feat(recipes): répertoire de recettes bash avec convention headers + toc.txt"
```

---

### Task 2 : Backend — store recipe-sources.yaml + endpoints CRUD

**Files:**
- Create: `backend/src/portal/routes/recipe_sources.py`
- Create: `backend/tests/recipe_sources/__init__.py`
- Create: `backend/tests/recipe_sources/test_recipe_sources.py`
- Modify: `backend/src/portal/app.py`

Le fichier `/data/recipe-sources.yaml` stocke la liste des URLs de `toc.txt`. Écriture atomique via `tempfile` + `os.replace`. URL par défaut = `https://raw.githubusercontent.com/gaelgael5/devpod-ui/dev/recipes/toc.txt`.

- [ ] **Step 1 : Écrire les tests (rouge)**

```python
# backend/tests/recipe_sources/__init__.py
# (vide)
```

```python
# backend/tests/recipe_sources/test_recipe_sources.py
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_sources_default(client: AsyncClient) -> None:
    resp = await client.get("/admin/recipe-sources", headers={"X-Test-Admin": "1"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["sources"], list)
    assert len(data["sources"]) >= 1
    assert any("toc.txt" in url for url in data["sources"])


@pytest.mark.asyncio
async def test_put_sources(client: AsyncClient) -> None:
    resp = await client.put(
        "/admin/recipe-sources",
        json={"sources": ["https://example.com/toc.txt"]},
        headers={"X-Test-Admin": "1"},
    )
    assert resp.status_code == 200
    assert resp.json()["sources"] == ["https://example.com/toc.txt"]


@pytest.mark.asyncio
async def test_get_sources_persisted(client: AsyncClient) -> None:
    await client.put(
        "/admin/recipe-sources",
        json={"sources": ["https://example.com/toc.txt"]},
        headers={"X-Test-Admin": "1"},
    )
    resp = await client.get("/admin/recipe-sources", headers={"X-Test-Admin": "1"})
    assert resp.json()["sources"] == ["https://example.com/toc.txt"]


@pytest.mark.asyncio
async def test_sources_requires_admin(client: AsyncClient) -> None:
    resp = await client.get("/admin/recipe-sources", headers={"X-Test-User": "alice"})
    assert resp.status_code == 403
```

Run: `cd backend && uv run pytest tests/recipe_sources/ -v`
Expected: FAIL (ImportError ou 404)

- [ ] **Step 2 : Créer `backend/src/portal/routes/recipe_sources.py`**

```python
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any

import structlog
import yaml
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from ..auth.rbac import UserInfo, require_admin
from ..config.store import _data_root

_log = structlog.get_logger(__name__)

router_admin = APIRouter(tags=["recipe-sources"])

_DEFAULT_SOURCE = (
    "https://raw.githubusercontent.com/gaelgael5/devpod-ui/dev/recipes/toc.txt"
)


class RecipeSourcesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[str]


def _sources_path() -> Path:
    return _data_root() / "recipe-sources.yaml"


def _load_sources() -> list[str]:
    path = _sources_path()
    if not path.exists():
        return [_DEFAULT_SOURCE]
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("sources", [_DEFAULT_SOURCE]))


def _save_sources(sources: list[str]) -> None:
    path = _sources_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(yaml.dump({"sources": sources}, default_flow_style=False))
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


@router_admin.get("/recipe-sources")
async def get_recipe_sources(
    user: UserInfo = Depends(require_admin),
) -> dict[str, Any]:
    sources = await asyncio.to_thread(_load_sources)
    return {"sources": sources}


@router_admin.put("/recipe-sources")
async def put_recipe_sources(
    body: RecipeSourcesPayload,
    user: UserInfo = Depends(require_admin),
) -> dict[str, Any]:
    await asyncio.to_thread(_save_sources, body.sources)
    _log.info("recipe_sources_updated", count=len(body.sources), by=user.login)
    return {"sources": body.sources}
```

- [ ] **Step 3 : Enregistrer le router dans `app.py`**

Dans `backend/src/portal/app.py`, ajouter après les autres imports de routes :
```python
from .routes.recipe_sources import router_admin as recipe_sources_admin_router
```

Et dans la section `include_router` :
```python
app.include_router(recipe_sources_admin_router, prefix="/admin")
```

- [ ] **Step 4 : Lancer les tests (vert)**

Run: `cd backend && uv run pytest tests/recipe_sources/ -v`
Expected: PASS (4/4)

- [ ] **Step 5 : Lint + mypy**

```bash
cd backend && uv run ruff check src/ && uv run mypy src/
```
Expected: no errors

- [ ] **Step 6 : Commit**

```bash
git add backend/src/portal/routes/recipe_sources.py backend/src/portal/app.py backend/tests/recipe_sources/
git commit -m "feat(recipes): store recipe-sources.yaml + endpoints CRUD admin"
```

---

### Task 3 : Backend — endpoint preview des sources distantes

**Files:**
- Modify: `backend/src/portal/routes/recipe_sources.py`
- Modify: `backend/tests/recipe_sources/test_recipe_sources.py`

Fetch chaque `toc.txt`, puis chaque `.sh` pour extraire `# name:`, `# description:`, `# version:`. Timeout 5s par requête. Erreurs isolées par source (une source en échec n'empêche pas les autres de s'afficher).

- [ ] **Step 1 : Écrire le test (rouge)**

Ajouter dans `backend/tests/recipe_sources/test_recipe_sources.py` :
```python
import respx
from httpx import Response


@pytest.mark.asyncio
@respx.mock
async def test_preview_sources(client: AsyncClient) -> None:
    toc_url = "https://example.com/recipes/toc.txt"
    sh_url = "https://example.com/recipes/git.sh"
    respx.get(toc_url).mock(return_value=Response(200, text="git.sh\n"))
    respx.get(sh_url).mock(return_value=Response(200, text=(
        "# name: Git\n"
        "# description: Configure Git\n"
        "# version: 1.0.0\n"
        "#!/usr/bin/env bash\nset -e\n"
    )))
    await client.put(
        "/admin/recipe-sources",
        json={"sources": [toc_url]},
        headers={"X-Test-Admin": "1"},
    )
    resp = await client.get(
        "/admin/recipe-sources/preview",
        headers={"X-Test-Admin": "1"},
    )
    assert resp.status_code == 200
    recipes = resp.json()["recipes"]
    assert len(recipes) == 1
    assert recipes[0]["id"] == "git"
    assert recipes[0]["name"] == "Git"
    assert recipes[0]["description"] == "Configure Git"
    assert recipes[0]["version"] == "1.0.0"
    assert recipes[0]["source_url"] == sh_url


@pytest.mark.asyncio
@respx.mock
async def test_preview_source_error_isolated(client: AsyncClient) -> None:
    """Une source en erreur n'empêche pas les autres."""
    good_toc = "https://good.example.com/toc.txt"
    bad_toc = "https://bad.example.com/toc.txt"
    sh_url = "https://good.example.com/ok.sh"
    respx.get(good_toc).mock(return_value=Response(200, text="ok.sh\n"))
    respx.get(sh_url).mock(return_value=Response(200, text=(
        "# name: OK\n# description: Works\n# version: 1.0.0\n#!/usr/bin/env bash\n"
    )))
    respx.get(bad_toc).mock(return_value=Response(500))
    await client.put(
        "/admin/recipe-sources",
        json={"sources": [good_toc, bad_toc]},
        headers={"X-Test-Admin": "1"},
    )
    resp = await client.get(
        "/admin/recipe-sources/preview",
        headers={"X-Test-Admin": "1"},
    )
    assert resp.status_code == 200
    assert len(resp.json()["recipes"]) == 1
```

Run: `cd backend && uv run pytest tests/recipe_sources/ -k "preview" -v`
Expected: FAIL

- [ ] **Step 2 : Ajouter le parsing + l'endpoint preview dans `recipe_sources.py`**

Ajouter ces imports en tête :
```python
import re
import httpx
```

Ajouter ces fonctions + endpoint :
```python
_HEADER_RE = re.compile(r"^#\s*(name|description|version)\s*:\s*(.+)$", re.MULTILINE)


def _parse_sh_headers(content: str) -> dict[str, str]:
    return {m.group(1): m.group(2).strip() for m in _HEADER_RE.finditer(content)}


async def _fetch_text(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url, timeout=5.0, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


async def _preview_one_source(
    client: httpx.AsyncClient, toc_url: str
) -> list[dict[str, Any]]:
    base = toc_url.rsplit("/", 1)[0]
    try:
        toc = await _fetch_text(client, toc_url)
    except Exception as exc:
        _log.warning("recipe_source_fetch_failed", url=toc_url, error=str(exc))
        return []
    results: list[dict[str, Any]] = []
    for line in toc.splitlines():
        fname = line.strip()
        if not fname or not fname.endswith(".sh"):
            continue
        sh_url = f"{base}/{fname}"
        try:
            content = await _fetch_text(client, sh_url)
        except Exception as exc:
            _log.warning("recipe_sh_fetch_failed", url=sh_url, error=str(exc))
            continue
        headers = _parse_sh_headers(content)
        recipe_id = fname[:-3]  # strip .sh
        results.append({
            "id": recipe_id,
            "name": headers.get("name", recipe_id),
            "description": headers.get("description", ""),
            "version": headers.get("version", "1.0.0"),
            "source_url": sh_url,
            "install_script": content,
        })
    return results


@router_admin.get("/recipe-sources/preview")
async def preview_recipe_sources(
    user: UserInfo = Depends(require_admin),
) -> dict[str, Any]:
    sources = await asyncio.to_thread(_load_sources)
    all_recipes: list[dict[str, Any]] = []
    async with httpx.AsyncClient() as http:
        for src_url in sources:
            recipes = await _preview_one_source(http, src_url)
            all_recipes.extend(recipes)
    return {"recipes": all_recipes}
```

- [ ] **Step 3 : Lancer les tests (vert)**

Run: `cd backend && uv run pytest tests/recipe_sources/ -v`
Expected: PASS (6/6)

- [ ] **Step 4 : Lint + mypy**

```bash
cd backend && uv run ruff check src/ && uv run mypy src/
```
Expected: no errors

- [ ] **Step 5 : Commit**

```bash
git add backend/src/portal/routes/recipe_sources.py backend/tests/recipe_sources/
git commit -m "feat(recipes): endpoint preview — fetch toc.txt + parse headers .sh"
```

---

### Task 4 : Backend — endpoint import avec gestion collision

**Files:**
- Modify: `backend/src/portal/routes/recipe_sources.py`
- Modify: `backend/tests/recipe_sources/test_recipe_sources.py`

`POST /admin/recipe-sources/import` — fetch le `.sh` depuis `source_url`, dérive l'`id` du filename. Si `id` existe déjà dans `/data/recipes/`, suffixe avec `-1`, `-2`, etc. Réutilise la logique d'écriture atomique de `admin_create_shared_recipe`.

- [ ] **Step 1 : Écrire les tests (rouge)**

Ajouter dans `backend/tests/recipe_sources/test_recipe_sources.py` :
```python
@pytest.mark.asyncio
@respx.mock
async def test_import_recipe(client: AsyncClient) -> None:
    sh_url = "https://example.com/recipes/git.sh"
    respx.get(sh_url).mock(return_value=Response(200, text=(
        "# name: Git\n# description: Configure Git\n# version: 1.0.0\n"
        "#!/usr/bin/env bash\nset -e\n"
    )))
    resp = await client.post(
        "/admin/recipe-sources/import",
        json={"source_url": sh_url},
        headers={"X-Test-Admin": "1"},
    )
    assert resp.status_code == 201
    assert resp.json()["id"] == "git"


@pytest.mark.asyncio
@respx.mock
async def test_import_recipe_collision(client: AsyncClient) -> None:
    sh_url = "https://example.com/recipes/git.sh"
    content = (
        "# name: Git\n# description: Configure Git\n# version: 1.0.0\n"
        "#!/usr/bin/env bash\nset -e\n"
    )
    respx.get(sh_url).mock(return_value=Response(200, text=content))
    r1 = await client.post(
        "/admin/recipe-sources/import",
        json={"source_url": sh_url},
        headers={"X-Test-Admin": "1"},
    )
    assert r1.json()["id"] == "git"

    respx.get(sh_url).mock(return_value=Response(200, text=content))
    r2 = await client.post(
        "/admin/recipe-sources/import",
        json={"source_url": sh_url},
        headers={"X-Test-Admin": "1"},
    )
    assert r2.json()["id"] == "git-1"
```

Run: `cd backend && uv run pytest tests/recipe_sources/ -k "import" -v`
Expected: FAIL

- [ ] **Step 2 : Ajouter l'endpoint import dans `recipe_sources.py`**

Ajouter imports supplémentaires :
```python
import json as _json
import shutil
from ..recipes.models import _RECIPE_ID_RE, RecipeMeta
```

Ajouter les fonctions + endpoint :
```python
class RecipeImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_url: str


def _unique_recipe_id(base_id: str, shared_dir: Path) -> str:
    if not (shared_dir / base_id).exists():
        return base_id
    counter = 1
    while (shared_dir / f"{base_id}-{counter}").exists():
        counter += 1
    return f"{base_id}-{counter}"


def _write_recipe(
    shared_dir: Path,
    recipe_id: str,
    version: str,
    description: str,
    install_script: str,
) -> None:
    recipe_path = shared_dir / recipe_id
    tmp = shared_dir / f".tmp-{recipe_id}"
    try:
        tmp.mkdir(parents=True, exist_ok=False)
        meta = RecipeMeta(id=recipe_id, version=version, description=description)
        (tmp / "recipe.meta.yaml").write_text(
            yaml.dump(meta.model_dump(), default_flow_style=False), encoding="utf-8"
        )
        (tmp / "devcontainer-feature.json").write_text(
            _json.dumps({"id": recipe_id, "version": version}, indent=2),
            encoding="utf-8",
        )
        install_sh = tmp / "install.sh"
        install_sh.write_text(install_script, encoding="utf-8")
        install_sh.chmod(0o755)
        tmp.rename(recipe_path)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


@router_admin.post("/recipe-sources/import", status_code=201)
async def import_recipe_from_source(
    body: RecipeImportRequest,
    user: UserInfo = Depends(require_admin),
) -> dict[str, Any]:
    from fastapi import HTTPException

    async with httpx.AsyncClient() as http:
        try:
            content = await _fetch_text(http, body.source_url)
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"Cannot fetch recipe: {exc}"
            ) from exc

    headers = _parse_sh_headers(content)
    fname = body.source_url.rsplit("/", 1)[-1]
    base_id = fname[:-3] if fname.endswith(".sh") else fname

    if not _RECIPE_ID_RE.fullmatch(base_id):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid recipe id derived from URL: {base_id!r}",
        )

    data_root = _data_root()
    shared_dir = data_root / "recipes"
    recipe_id = await asyncio.to_thread(_unique_recipe_id, base_id, shared_dir)

    await asyncio.to_thread(
        _write_recipe,
        shared_dir,
        recipe_id,
        headers.get("version", "1.0.0"),
        headers.get("description", ""),
        content,
    )
    _log.info("recipe_imported", recipe_id=recipe_id, source=body.source_url, by=user.login)
    return {
        "id": recipe_id,
        "version": headers.get("version", "1.0.0"),
        "description": headers.get("description", ""),
    }
```

- [ ] **Step 3 : Lancer les tests (vert)**

Run: `cd backend && uv run pytest tests/recipe_sources/ -v`
Expected: PASS (8/8)

- [ ] **Step 4 : Lint + mypy**

```bash
cd backend && uv run ruff check src/ && uv run mypy src/
```
Expected: no errors

- [ ] **Step 5 : Commit**

```bash
git add backend/src/portal/routes/recipe_sources.py backend/tests/recipe_sources/
git commit -m "feat(recipes): import depuis source distante avec gestion collision id"
```

---

### Task 5 : Backend — endpoint logs workspace

**Files:**
- Modify: `backend/src/portal/routes/workspace_ops.py`

`GET /me/workspaces/{name}/logs` — lit le fichier de log depuis `_data_root() / "logs" / {login} / {login}-{name}.log`. Retourne le contenu en texte brut, limité aux 100 derniers Ko. Le `ws_id` suit le pattern `{login}-{name}` (comme dans `service.py`).

- [ ] **Step 1 : Écrire les tests (rouge)**

Dans le fichier de tests existant des workspace_ops (ou créer `backend/tests/workspace_ops/test_logs.py`) :
```python
# backend/tests/workspace_ops/test_logs.py
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_workspace_logs_not_found(client: AsyncClient) -> None:
    resp = await client.get(
        "/me/workspaces/no-such-ws/logs",
        headers={"X-Test-User": "alice"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_workspace_logs(client: AsyncClient, data_root: Path) -> None:
    # data_root est la fixture tmpdir utilisée dans les tests existants
    log_dir = data_root / "logs" / "alice"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "alice-my-ws.log").write_text("Line 1\nLine 2\n", encoding="utf-8")
    resp = await client.get(
        "/me/workspaces/my-ws/logs",
        headers={"X-Test-User": "alice"},
    )
    assert resp.status_code == 200
    assert "Line 1" in resp.text
    assert "Line 2" in resp.text


@pytest.mark.asyncio
async def test_get_workspace_logs_invalid_name(client: AsyncClient) -> None:
    resp = await client.get(
        "/me/workspaces/../etc/logs",
        headers={"X-Test-User": "alice"},
    )
    assert resp.status_code in (404, 422)
```

Run: `cd backend && uv run pytest tests/workspace_ops/test_logs.py -v`
Expected: FAIL

**Note :** Vérifier comment la fixture `data_root` ou `tmp_path` est exposée dans le conftest existant avant d'écrire le test — adapter si nécessaire.

- [ ] **Step 2 : Implémenter l'endpoint**

Dans `backend/src/portal/routes/workspace_ops.py`, ajouter l'import :
```python
from fastapi.responses import PlainTextResponse
```

Ajouter l'endpoint (après les routes existantes) :
```python
@router.get("/me/workspaces/{name}/logs", response_class=PlainTextResponse)
async def get_workspace_logs(
    name: str,
    user: UserInfo = Depends(require_user),
) -> str:
    _validate_name(name)
    ws_id = f"{user.login}-{name}"
    log_file = _data_root() / "logs" / user.login / f"{ws_id}.log"
    if not log_file.exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    content = await asyncio.to_thread(
        log_file.read_text, encoding="utf-8", errors="replace"
    )
    # Limité aux 100 derniers Ko pour éviter des réponses trop volumineuses
    return content[-100_000:]
```

- [ ] **Step 3 : Lancer les tests (vert)**

Run: `cd backend && uv run pytest tests/workspace_ops/test_logs.py -v`
Expected: PASS (3/3)

- [ ] **Step 4 : Lint + mypy**

```bash
cd backend && uv run ruff check src/ && uv run mypy src/
```
Expected: no errors

- [ ] **Step 5 : Commit**

```bash
git add backend/src/portal/routes/workspace_ops.py backend/tests/workspace_ops/test_logs.py
git commit -m "feat(workspace): endpoint GET /me/workspaces/{name}/logs"
```

---

### Task 6 : Frontend — hooks useRecipeSources + useWorkspaceLogs

**Files:**
- Create: `frontend/src/features/admin/useRecipeSources.ts`
- Create: `frontend/src/features/workspaces/useWorkspaceLogs.ts`

- [ ] **Step 1 : Créer `frontend/src/features/admin/useRecipeSources.ts`**

```typescript
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiFetchJson } from '@/shared/api/client'

export interface RemoteRecipe {
  id: string
  name: string
  description: string
  version: string
  source_url: string
  install_script: string
}

export function useRecipeSources() {
  const qc = useQueryClient()

  const sourcesQuery = useQuery<{ sources: string[] }>({
    queryKey: ['admin', 'recipe-sources'],
    queryFn: () => apiFetchJson<{ sources: string[] }>('/admin/recipe-sources'),
    staleTime: 5 * 60 * 1000,
  })

  const updateSources = useMutation({
    mutationFn: (sources: string[]) =>
      apiFetchJson<{ sources: string[] }>('/admin/recipe-sources', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sources }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'recipe-sources'] }),
    onError: (err: Error) => toast.error(err.message),
  })

  const previewQuery = useQuery<{ recipes: RemoteRecipe[] }>({
    queryKey: ['admin', 'recipe-sources', 'preview'],
    queryFn: () =>
      apiFetchJson<{ recipes: RemoteRecipe[] }>('/admin/recipe-sources/preview'),
    staleTime: 2 * 60 * 1000,
  })

  const importRecipe = useMutation({
    mutationFn: (source_url: string) =>
      apiFetchJson<{ id: string }>('/admin/recipe-sources/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_url }),
      }),
    onSuccess: (data) => {
      toast.success(`Recette "${data.id}" importée`)
      qc.invalidateQueries({ queryKey: ['admin', 'recipes'] })
      qc.invalidateQueries({ queryKey: ['admin', 'recipe-sources', 'preview'] })
    },
    onError: (err: Error) => toast.error(err.message),
  })

  return { sourcesQuery, updateSources, previewQuery, importRecipe }
}
```

- [ ] **Step 2 : Créer `frontend/src/features/workspaces/useWorkspaceLogs.ts`**

```typescript
import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '@/shared/api/client'

export function useWorkspaceLogs(name: string, enabled: boolean) {
  return useQuery<string>({
    queryKey: ['workspace-logs', name],
    queryFn: async () => {
      const resp = await apiFetch(`/me/workspaces/${name}/logs`)
      return resp.text()
    },
    enabled,
    staleTime: 0,
    refetchInterval: enabled ? 3000 : false,
  })
}
```

- [ ] **Step 3 : TypeScript check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 4 : Commit**

```bash
git add frontend/src/features/admin/useRecipeSources.ts frontend/src/features/workspaces/useWorkspaceLogs.ts
git commit -m "feat(recipes): hooks useRecipeSources + useWorkspaceLogs"
```

---

### Task 7 : Frontend — redesign AdminRecipes (sources + galerie + local)

**Files:**
- Modify: `frontend/src/features/admin/AdminRecipes.tsx`
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

Structure de la page :
1. Section **Sources** : liste des URLs (lecture seule avec bouton supprimer) + champ d'ajout
2. Section **Galerie** : bouton Rafraîchir + grille de cartes recettes distantes avec bouton "Importer"
3. Section **Recettes locales** : grille des recettes locales avec Edit + Delete (+ dialog edit inchangé)

Le bouton "Ajouter une recette" disparaît (les recettes viennent de l'import ou de la galerie uniquement).

- [ ] **Step 1 : Ajouter les clés i18n**

Dans `fr.json`, ajouter sous `"admin"` :
```json
"gallery": "Galerie",
"localRecipes": "Recettes locales",
"recipeSource": "Sources de recettes",
"addSource": "Ajouter",
"importRecipe": "Importer",
"importing": "Import…",
"refreshGallery": "Rafraîchir"
```

Dans `en.json`, ajouter sous `"admin"` :
```json
"gallery": "Gallery",
"localRecipes": "Local recipes",
"recipeSource": "Recipe sources",
"addSource": "Add",
"importRecipe": "Import",
"importing": "Importing…",
"refreshGallery": "Refresh"
```

- [ ] **Step 2 : Réécrire `AdminRecipes.tsx`**

```tsx
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, Trash2, RefreshCw } from 'lucide-react'
import Editor from 'react-simple-code-editor'
import Prism from 'prismjs'
import 'prismjs/components/prism-bash'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import type { Recipe } from '@/features/recipes/types'
import { useAdminRecipes, type RecipeCreateRequest } from './useAdminRecipes'
import { useRecipeSources, type RemoteRecipe } from './useRecipeSources'

const DEFAULT_SCRIPT = '#!/usr/bin/env bash\nset -e\necho "Installing..."\n'

interface FormState {
  id: string
  version: string
  description: string
  install_script: string
}

const EMPTY: FormState = {
  id: '',
  version: '1.0.0',
  description: '',
  install_script: DEFAULT_SCRIPT,
}

function recipeToForm(r: Recipe): FormState {
  return {
    id: r.id,
    version: r.version,
    description: r.description,
    install_script: r.install_script ?? DEFAULT_SCRIPT,
  }
}

export default function AdminRecipes() {
  const { t } = useTranslation()
  const { recipesQuery, deleteRecipe, addRecipe, updateRecipe } = useAdminRecipes()
  const { sourcesQuery, updateSources, previewQuery, importRecipe } = useRecipeSources()
  const { data: recipes, isLoading, isError } = recipesQuery
  const { data: sourcesData } = sourcesQuery
  const {
    data: previewData,
    isFetching: isLoadingGallery,
    refetch: refetchGallery,
  } = previewQuery

  const [editingId, setEditingId] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<FormState>(EMPTY)
  const [newSourceUrl, setNewSourceUrl] = useState('')

  const sources = sourcesData?.sources ?? []
  const galleryRecipes = previewData?.recipes ?? []
  const isEditing = editingId !== null
  const isPending = addRecipe.isPending || updateRecipe.isPending

  function openEdit(recipe: Recipe) {
    setEditingId(recipe.id)
    setForm(recipeToForm(recipe))
    setOpen(true)
  }

  function handleClose(o: boolean) {
    if (!o) {
      setOpen(false)
      setEditingId(null)
      setForm(EMPTY)
    } else {
      setOpen(true)
    }
  }

  function set<K extends keyof FormState>(k: K, v: FormState[K]) {
    setForm((f) => ({ ...f, [k]: v }))
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (isEditing) {
      updateRecipe.mutate(form, { onSuccess: () => handleClose(false) })
    } else {
      addRecipe.mutate(form as RecipeCreateRequest, { onSuccess: () => handleClose(false) })
    }
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

  return (
    <div className="flex flex-col gap-10">

      {/* ── Sources ─────────────────────────────────────────────────── */}
      <section>
        <h2 className="mb-3 text-lg font-semibold">{t('admin.recipeSource')}</h2>
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
                aria-label="Supprimer la source"
              >
                <Trash2 className="h-4 w-4 text-destructive" />
              </Button>
            </div>
          ))}
          <div className="flex items-center gap-2">
            <Input
              value={newSourceUrl}
              onChange={(e) => setNewSourceUrl(e.target.value)}
              placeholder="https://raw.githubusercontent.com/…/toc.txt"
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
          <h2 className="text-lg font-semibold">{t('admin.gallery')}</h2>
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
        {!isLoadingGallery && galleryRecipes.length === 0 && (
          <p className="text-sm text-muted-foreground">{t('admin.recipesEmpty')}</p>
        )}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {galleryRecipes.map((r: RemoteRecipe) => (
            <div key={r.source_url} className="rounded-lg border bg-card p-4">
              <div className="mb-1 flex items-start justify-between gap-2">
                <div>
                  <div className="font-medium">{r.name}</div>
                  <div className="text-xs text-muted-foreground font-mono">{r.id}</div>
                </div>
                <Button
                  size="sm"
                  onClick={() => importRecipe.mutate(r.source_url)}
                  disabled={importRecipe.isPending}
                >
                  {importRecipe.isPending
                    ? t('admin.importing')
                    : t('admin.importRecipe')}
                </Button>
              </div>
              <div className="text-sm text-muted-foreground">{r.description}</div>
              <div className="mt-2 text-xs text-muted-foreground">v{r.version}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ── Recettes locales ────────────────────────────────────────── */}
      <section>
        <h2 className="mb-3 text-lg font-semibold">{t('admin.localRecipes')}</h2>
        {isLoading && <p className="text-muted-foreground">…</p>}
        {isError && (
          <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>
        )}
        {!isLoading && !isError && !recipes?.length && (
          <p className="text-muted-foreground">{t('admin.recipesEmpty')}</p>
        )}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {recipes?.map((recipe: Recipe) => (
            <div key={recipe.id} className="rounded-lg border bg-card p-4">
              <div className="mb-1 flex items-start justify-between gap-2">
                <div className="font-medium">{recipe.id}</div>
                <div className="flex gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => openEdit(recipe)}
                  >
                    {t('workspaces.actions.edit')}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-destructive hover:text-destructive"
                    onClick={() => deleteRecipe.mutate(recipe.id)}
                    disabled={deleteRecipe.isPending}
                  >
                    {t('workspaces.actions.delete')}
                  </Button>
                </div>
              </div>
              <div className="text-sm text-muted-foreground">{recipe.description}</div>
              <div className="mt-2 text-xs text-muted-foreground">v{recipe.version}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ── Dialog édition recette locale ───────────────────────────── */}
      <Dialog open={open} onOpenChange={handleClose}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {isEditing ? t('admin.editRecipe') : t('admin.addRecipe')}
            </DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="r-id">{t('admin.form.recipeId')}</Label>
              <Input
                id="r-id"
                value={form.id}
                onChange={(e) => set('id', e.target.value)}
                placeholder="my-tool"
                pattern="^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$"
                required
                readOnly={isEditing}
                className={isEditing ? 'opacity-60 cursor-not-allowed' : ''}
              />
            </div>
            <div className="flex gap-4">
              <div className="flex flex-1 flex-col gap-1.5">
                <Label htmlFor="r-version">{t('admin.form.version')}</Label>
                <Input
                  id="r-version"
                  value={form.version}
                  onChange={(e) => set('version', e.target.value)}
                  required
                />
              </div>
              <div className="flex flex-1 flex-col gap-1.5">
                <Label htmlFor="r-desc">{t('admin.form.description')}</Label>
                <Input
                  id="r-desc"
                  value={form.description}
                  onChange={(e) => set('description', e.target.value)}
                />
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>{t('admin.form.installScript')}</Label>
              <div
                className="bash-editor overflow-auto rounded-md border border-input bg-zinc-950 shadow-sm focus-within:ring-1 focus-within:ring-ring"
                style={{ minHeight: '220px', maxHeight: '420px' }}
              >
                <Editor
                  value={form.install_script}
                  onValueChange={(v) => set('install_script', v)}
                  highlight={(code) =>
                    Prism.highlight(code, Prism.languages.bash, 'bash')
                  }
                  padding={12}
                  style={{
                    color: '#d4d4d4',
                    background: 'transparent',
                    minHeight: '220px',
                  }}
                />
              </div>
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => handleClose(false)}
              >
                {t('workspaces.confirm.cancel')}
              </Button>
              <Button type="submit" disabled={isPending}>
                {t('admin.form.save')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
```

- [ ] **Step 3 : TypeScript check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 4 : Commit**

```bash
git add frontend/src/features/admin/AdminRecipes.tsx frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(admin): redesign AdminRecipes — sources + galerie + recettes locales"
```

---

### Task 8 : Frontend — picker ordonné de recettes dans WorkspaceCreate

**Files:**
- Create: `frontend/src/features/recipes/OrderedRecipePicker.tsx`
- Modify: `frontend/src/features/workspaces/WorkspaceCreate.tsx`
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

Le picker ordonné remplace `RecipePicker` dans `WorkspaceCreate`. Il affiche une liste numérotée des recettes sélectionnées + un bouton "Ajouter une recette" qui ouvre un Dialog modal listant les recettes non encore sélectionnées. L'ordre de la liste détermine l'ordre d'installation.

- [ ] **Step 1 : Ajouter les clés i18n**

Dans `fr.json`, sous `workspaces.form` :
```json
"addRecipe": "Ajouter une recette",
"noMoreRecipes": "Toutes les recettes sont déjà sélectionnées."
```

Dans `en.json`, sous `workspaces.form` :
```json
"addRecipe": "Add recipe",
"noMoreRecipes": "All recipes already selected."
```

- [ ] **Step 2 : Créer `frontend/src/features/recipes/OrderedRecipePicker.tsx`**

```tsx
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { Recipe } from './types'

interface Props {
  recipes: Recipe[]
  selected: string[]
  onChange: (selected: string[]) => void
}

export default function OrderedRecipePicker({ recipes, selected, onChange }: Props) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)

  const recipeById = new Map(recipes.map((r) => [r.id, r]))
  const available = recipes.filter((r) => !selected.includes(r.id))

  function add(id: string) {
    onChange([...selected, id])
    setOpen(false)
  }

  function remove(id: string) {
    onChange(selected.filter((r) => r !== id))
  }

  return (
    <div className="flex flex-col gap-2">
      {selected.length > 0 && (
        <ol className="flex flex-col gap-1">
          {selected.map((id, idx) => {
            const recipe = recipeById.get(id)
            return (
              <li
                key={id}
                className="flex items-center gap-2 rounded-md border bg-card px-3 py-1.5 text-sm"
              >
                <span className="w-5 shrink-0 text-right text-xs text-muted-foreground">
                  {idx + 1}.
                </span>
                <span className="flex-1 font-medium">{id}</span>
                {recipe?.description && (
                  <span className="max-w-[180px] truncate text-xs text-muted-foreground">
                    {recipe.description}
                  </span>
                )}
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-6 w-6 shrink-0"
                  onClick={() => remove(id)}
                  aria-label={`Retirer ${id}`}
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              </li>
            )
          })}
        </ol>
      )}

      <Button
        type="button"
        variant="outline"
        size="sm"
        className="self-start"
        onClick={() => setOpen(true)}
      >
        <Plus className="mr-1 h-3.5 w-3.5" />
        {t('workspaces.form.addRecipe')}
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('workspaces.form.addRecipe')}</DialogTitle>
          </DialogHeader>
          {available.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t('workspaces.form.noMoreRecipes')}
            </p>
          ) : (
            <div className="flex max-h-80 flex-col gap-2 overflow-y-auto">
              {available.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  onClick={() => add(r.id)}
                  className="flex flex-col gap-0.5 rounded-md border bg-card px-3 py-2 text-left transition-colors hover:bg-accent"
                >
                  <span className="text-sm font-medium">{r.id}</span>
                  {r.description && (
                    <span className="text-xs text-muted-foreground">
                      {r.description}
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
```

- [ ] **Step 3 : Remplacer `RecipePicker` par `OrderedRecipePicker` dans `WorkspaceCreate.tsx`**

Remplacer la ligne d'import :
```tsx
// Avant
import RecipePicker from '@/features/recipes/RecipePicker'
// Après
import OrderedRecipePicker from '@/features/recipes/OrderedRecipePicker'
```

Remplacer l'utilisation dans le JSX :
```tsx
// Avant
<RecipePicker
  recipes={recipes}
  selected={selectedRecipes}
  onChange={setSelectedRecipes}
/>
// Après
<OrderedRecipePicker
  recipes={recipes}
  selected={selectedRecipes}
  onChange={setSelectedRecipes}
/>
```

- [ ] **Step 4 : TypeScript check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 5 : Commit**

```bash
git add frontend/src/features/recipes/OrderedRecipePicker.tsx frontend/src/features/workspaces/WorkspaceCreate.tsx frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(workspace): picker de recettes ordonné dans WorkspaceCreate"
```

---

### Task 9 : Frontend — bouton Logs + LogDialog dans WorkspaceCard

**Files:**
- Create: `frontend/src/features/workspaces/LogDialog.tsx`
- Modify: `frontend/src/features/workspaces/WorkspaceCard.tsx`
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

Le bouton Logs est présent sur toutes les cartes workspace. `LogDialog` affiche le contenu texte en monospace sur fond sombre, avec auto-refresh toutes les 3s tant que le dialog est ouvert.

- [ ] **Step 1 : Ajouter les clés i18n**

Dans `fr.json`, sous `workspaces` :
```json
"logs": {
  "button": "Logs",
  "title": "Logs — {{name}}",
  "empty": "Aucun log disponible pour ce workspace.",
  "loading": "Chargement…"
}
```

Dans `en.json`, sous `workspaces` :
```json
"logs": {
  "button": "Logs",
  "title": "Logs — {{name}}",
  "empty": "No logs available for this workspace.",
  "loading": "Loading…"
}
```

- [ ] **Step 2 : Créer `frontend/src/features/workspaces/LogDialog.tsx`**

```tsx
import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useWorkspaceLogs } from './useWorkspaceLogs'

interface Props {
  workspaceName: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export default function LogDialog({ workspaceName, open, onOpenChange }: Props) {
  const { t } = useTranslation()
  const { data: logs, isLoading } = useWorkspaceLogs(workspaceName, open)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (logs) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            {t('workspaces.logs.title', { name: workspaceName })}
          </DialogTitle>
        </DialogHeader>
        <div className="max-h-[60vh] overflow-auto rounded-md bg-zinc-950 p-3">
          {isLoading && !logs && (
            <p className="text-xs text-zinc-400">
              {t('workspaces.logs.loading')}
            </p>
          )}
          {!isLoading && !logs && (
            <p className="text-xs text-zinc-400">
              {t('workspaces.logs.empty')}
            </p>
          )}
          {logs && (
            <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-zinc-200">
              {logs}
            </pre>
          )}
          <div ref={bottomRef} />
        </div>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 3 : Modifier `WorkspaceCard.tsx`**

Remplacer la ligne d'import lucide existante :
```tsx
// Avant
import { Key } from 'lucide-react'
// Après
import { FileText, Key } from 'lucide-react'
```

Ajouter l'import de `LogDialog` après les autres imports de composants locaux :
```tsx
import LogDialog from './LogDialog'
```

Ajouter le state `logsOpen` après `sshKeyOpen` :
```tsx
const [logsOpen, setLogsOpen] = useState(false)
```

Ajouter le bouton Logs dans `<div className="flex gap-2">` (après le bouton SSH Key) :
```tsx
<Button
  size="sm"
  variant="ghost"
  onClick={() => setLogsOpen(true)}
  aria-label={t('workspaces.logs.button')}
>
  <FileText className="h-4 w-4" />
</Button>
```

Ajouter `LogDialog` juste après `SshKeyDialog` :
```tsx
<LogDialog
  workspaceName={spec.name}
  open={logsOpen}
  onOpenChange={setLogsOpen}
/>
```

- [ ] **Step 4 : TypeScript check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 5 : Commit**

```bash
git add frontend/src/features/workspaces/LogDialog.tsx frontend/src/features/workspaces/WorkspaceCard.tsx frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(workspace): bouton Logs + LogDialog avec auto-refresh dans WorkspaceCard"
```

---

## Self-Review

### Couverture spec

| Exigence | Tâche |
|---|---|
| `recipes/` avec `.sh` + `# name/description/version` | Task 1 |
| `toc.txt` (un filename par ligne) | Task 1 |
| URL par défaut `…/dev/recipes/toc.txt` | Task 2 |
| Admin gère liste d'URLs sources (CRUD) | Task 2 |
| Preview fetch distant avec parsing headers | Task 3 |
| Import avec gestion collision → suffix `-1`, `-2` | Task 4 |
| Endpoint logs `/me/workspaces/{name}/logs` | Task 5 |
| Hook `useRecipeSources` + `useWorkspaceLogs` | Task 6 |
| AdminRecipes : sources + galerie + local (pas de bouton "Ajouter") | Task 7 |
| WorkspaceCreate : picker ordonné (liste + modal) | Task 8 |
| WorkspaceCard : bouton Logs + LogDialog auto-refresh | Task 9 |

### Points de vigilance
- Task 5 : adapter le test à la fixture `data_root` réelle du conftest existant (à vérifier avant d'écrire le test)
- Task 4 : `_RECIPE_ID_RE` doit accepter les ids issus des filenames `.sh` — les scripts de la galerie ont des noms valides (`git`, `node`, `python`, `docker`)
- Task 8 : `RecipePicker` reste dans le codebase (utilisé potentiellement ailleurs) — seul `WorkspaceCreate` switche sur `OrderedRecipePicker`
