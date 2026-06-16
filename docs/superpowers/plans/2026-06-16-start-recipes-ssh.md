# Sessions SSH persistantes + recettes `start` — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre d'ouvrir des sessions SSH persistantes (via tmux) dans les workspaces, pilotées par des recettes `start` (scripts de démarrage) sélectionnables au lancement.

**Architecture:** On ajoute un champ `type: "install"|"start"` à `RecipeMeta` (rétrocompat). Les recettes `start` ont un `start.sh` (pas de `devcontainer-feature.json`). `WorkspaceSpec` gagne `start_recipes` + `default_start`. Une nouvelle route WebSocket `/me/workspaces/{name}/ssh` exécute `devpod ssh <ws_id> --command 'tmux new -A -s ...'` en bridgeant le PTY vers le WebSocket, exactement comme `ssh_proxy.py` pour les hôtes. Le frontend ajoute « Open VSCode » (renommage), « New SSH session » (menu dropdown), et un picker de recettes `start` dans le formulaire de création.

**Tech Stack:** FastAPI + pydantic v2 + asyncio · React 18 + TypeScript strict + shadcn/ui + xterm.js + TanStack Query · i18next · pytest

---

## Structure des fichiers

### Backend — créés
- `backend/src/portal/routes/workspace_ssh.py` — WebSocket `/workspaces/{name}/ssh`
- `backend/tests/routes/test_workspace_ssh.py` — tests WebSocket

### Backend — modifiés
- `backend/src/portal/recipes/models.py` — champ `type`
- `backend/src/portal/recipes/registry.py` — validation fichiers + `filter_by_type`
- `backend/src/portal/config/models.py` — `WorkspaceSpec.start_recipes` + `default_start`
- `backend/src/portal/routes/recipes.py` — filtre `?type=`, `POST /me/start-recipes`, admin create start
- `backend/src/portal/routes/workspace_ops.py` — `GET /workspaces/{name}/start-recipes`
- `backend/src/portal/app.py` — enregistrement `workspace_ssh_router`
- `backend/tests/recipes/test_models.py` — tests `type`
- `backend/tests/recipes/test_registry.py` — tests validation `start`
- `backend/tests/routes/test_recipes.py` — tests filtre + `POST /me/start-recipes`
- `backend/tests/routes/test_workspace_ops.py` — tests `GET /start-recipes`

### Frontend — créés
- `frontend/src/features/workspaces/WorkspaceSshTerminalWindow.tsx`
- `frontend/src/features/workspaces/useStartRecipes.ts`

### Frontend — modifiés
- `frontend/src/features/workspaces/types.ts` — `start_recipes`, `default_start`
- `frontend/src/features/workspaces/useWorkspaceOps.ts` — `start_recipes` dans `CreateInput`
- `frontend/src/features/workspaces/WorkspaceCard.tsx` — rename Open, SSH menu
- `frontend/src/features/workspaces/WorkspaceCreate.tsx` — picker start recipes + création inline
- `frontend/src/i18n/en.json` + `fr.json`

---

## Task 1 — `RecipeMeta.type` + `WorkspaceSpec.start_recipes`

**Files:**
- Modify: `backend/src/portal/recipes/models.py`
- Modify: `backend/src/portal/config/models.py`
- Modify: `backend/tests/recipes/test_models.py`
- Modify: `backend/tests/config/test_models.py` (ou créer si absent)

- [ ] **Step 1 : Écrire les tests qui vont échouer**

Dans `backend/tests/recipes/test_models.py`, ajouter à la fin :

```python
def test_recipe_meta_type_defaults_to_install() -> None:
    from portal.recipes.models import RecipeMeta

    meta = RecipeMeta(id="my-recipe")
    assert meta.type == "install"


def test_recipe_meta_type_start_accepted() -> None:
    from portal.recipes.models import RecipeMeta

    meta = RecipeMeta(id="claude-rc", type="start")
    assert meta.type == "start"


def test_recipe_meta_type_invalid_rejected() -> None:
    from pydantic import ValidationError

    from portal.recipes.models import RecipeMeta

    with pytest.raises(ValidationError):
        RecipeMeta(id="bad", type="unknown")
```

Dans `backend/tests/config/test_models.py`, ajouter :

```python
def test_workspace_spec_start_recipes_defaults_empty() -> None:
    from portal.config.models import WorkspaceSpec

    ws = WorkspaceSpec(name="my-ws", source="https://github.com/x/y")
    assert ws.start_recipes == []
    assert ws.default_start == ""


def test_workspace_spec_start_recipes_accepts_ids() -> None:
    from portal.config.models import WorkspaceSpec

    ws = WorkspaceSpec(
        name="my-ws",
        source="https://github.com/x/y",
        start_recipes=["claude-rc", "aider-rc"],
    )
    assert ws.start_recipes == ["claude-rc", "aider-rc"]


def test_workspace_spec_start_recipe_invalid_id_rejected() -> None:
    from pydantic import ValidationError

    from portal.config.models import WorkspaceSpec

    with pytest.raises(ValidationError, match="start_recipes"):
        WorkspaceSpec(
            name="my-ws",
            source="https://github.com/x/y",
            start_recipes=["../evil"],
        )
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```
cd backend && uv run pytest tests/recipes/test_models.py::test_recipe_meta_type_defaults_to_install tests/config/test_models.py::test_workspace_spec_start_recipes_defaults_empty -v
```
Attendu : FAIL (AttributeError: `type` not found)

- [ ] **Step 3 : Implémenter `RecipeMeta.type`**

Dans `backend/src/portal/recipes/models.py`, modifier la classe `RecipeMeta` :

```python
from typing import Any, Literal   # ajouter Literal

class RecipeMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: str = "1.0.0"
    description: str = ""
    type: Literal["install", "start"] = "install"   # ← nouveau champ
    options: dict[str, RecipeOption] = Field(default_factory=dict)
    requires_secrets: list[SecretRef] = Field(default_factory=list)
    installs_after: list[str] = Field(default_factory=list)
    # ... validators inchangés
```

- [ ] **Step 4 : Implémenter `WorkspaceSpec.start_recipes` + `default_start`**

Dans `backend/src/portal/config/models.py`, dans la classe `WorkspaceSpec` (après `profile: ProfileRef | None = None`) :

```python
start_recipes: list[str] = Field(default_factory=list)
default_start: str = ""

@field_validator("start_recipes")
@classmethod
def validate_start_recipe_ids(cls, v: list[str]) -> list[str]:
    from portal.recipes.models import _RECIPE_ID_RE

    for rid in v:
        if not _RECIPE_ID_RE.fullmatch(rid):
            raise ValueError(
                f"start_recipes: id {rid!r} must match"
                " ^[a-z0-9]([a-z0-9-]{{0,38}}[a-z0-9])?$"
            )
    return v
```

- [ ] **Step 5 : Vérifier que les tests passent**

```
cd backend && uv run pytest tests/recipes/test_models.py tests/config/test_models.py -v
```
Attendu : tous PASS

- [ ] **Step 6 : Commit**

```bash
git add backend/src/portal/recipes/models.py backend/src/portal/config/models.py backend/tests/recipes/test_models.py backend/tests/config/test_models.py
git commit -m "feat: RecipeMeta.type + WorkspaceSpec.start_recipes/default_start"
```

---

## Task 2 — `RecipeRegistry` : validation fichiers `start` + `filter_by_type`

**Files:**
- Modify: `backend/src/portal/recipes/registry.py`
- Modify: `backend/tests/recipes/test_registry.py`

- [ ] **Step 1 : Écrire les tests**

Dans `backend/tests/recipes/test_registry.py`, ajouter une fonction helper et les tests :

```python
def _write_start_recipe(base: Path, recipe_id: str) -> None:
    """Écrit une recette de type start valide."""
    d = base / recipe_id
    d.mkdir(parents=True, exist_ok=True)
    meta = {"id": recipe_id, "version": "1.0.0", "description": "start recipe", "type": "start"}
    (d / "recipe.meta.yaml").write_text(yaml.dump(meta), encoding="utf-8")
    (d / "start.sh").write_text("#!/usr/bin/env bash\nexec claude --rc\n", encoding="utf-8")


def test_load_dir_accepts_valid_start_recipe(tmp_path: Path) -> None:
    from portal.recipes.registry import RecipeRegistry

    _write_start_recipe(tmp_path, "claude-rc")
    registry = RecipeRegistry()
    result = registry.load_dir(tmp_path)
    assert "claude-rc" in result
    assert result["claude-rc"].type == "start"


def test_load_dir_rejects_start_recipe_without_start_sh(tmp_path: Path) -> None:
    from portal.recipes.registry import RecipeRegistry

    d = tmp_path / "bad-start"
    d.mkdir()
    (d / "recipe.meta.yaml").write_text(
        yaml.dump({"id": "bad-start", "type": "start"}), encoding="utf-8"
    )
    # Pas de start.sh
    registry = RecipeRegistry()
    result = registry.load_dir(tmp_path)
    assert "bad-start" not in result  # ignorée (log warning)


def test_load_dir_rejects_start_recipe_with_feature_json(tmp_path: Path) -> None:
    from portal.recipes.registry import RecipeRegistry

    import json as _json

    d = tmp_path / "bad-start2"
    d.mkdir()
    (d / "recipe.meta.yaml").write_text(
        yaml.dump({"id": "bad-start2", "type": "start"}), encoding="utf-8"
    )
    (d / "start.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (d / "devcontainer-feature.json").write_text(_json.dumps({"id": "bad-start2"}), encoding="utf-8")
    registry = RecipeRegistry()
    result = registry.load_dir(tmp_path)
    assert "bad-start2" not in result


def test_filter_by_type_returns_only_matching(tmp_path: Path) -> None:
    from portal.recipes.registry import RecipeRegistry

    _write_recipe(tmp_path, "my-install")
    _write_start_recipe(tmp_path, "my-start")
    registry = RecipeRegistry()
    all_recipes = registry.load_dir(tmp_path)
    starts = RecipeRegistry.filter_by_type(all_recipes, "start")
    installs = RecipeRegistry.filter_by_type(all_recipes, "install")
    assert set(starts.keys()) == {"my-start"}
    assert set(installs.keys()) == {"my-install"}
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```
cd backend && uv run pytest tests/recipes/test_registry.py::test_load_dir_accepts_valid_start_recipe tests/recipes/test_registry.py::test_filter_by_type_returns_only_matching -v
```
Attendu : FAIL

- [ ] **Step 3 : Implémenter la validation + `filter_by_type`**

Dans `backend/src/portal/recipes/registry.py`, modifier `_load_meta` et ajouter `filter_by_type` :

```python
@staticmethod
def _load_meta(recipe_dir: Path) -> RecipeMeta | None:
    meta_file = recipe_dir / "recipe.meta.yaml"
    if not meta_file.exists():
        return None
    try:
        data: object = yaml.safe_load(meta_file.read_text(encoding="utf-8"))
        meta = RecipeMeta.model_validate(data)
    except Exception as exc:
        _log.warning("recipe_meta_invalid", path=str(meta_file), error=str(exc))
        return None

    # Validation structure fichiers selon le type
    if meta.type == "start":
        if not (recipe_dir / "start.sh").exists():
            _log.warning("recipe_start_missing_start_sh", path=str(recipe_dir))
            return None
        if (recipe_dir / "devcontainer-feature.json").exists():
            _log.warning("recipe_start_has_feature_json", path=str(recipe_dir))
            return None

    return meta

@staticmethod
def filter_by_type(
    recipes: dict[str, RecipeMeta],
    type_filter: str,
) -> dict[str, RecipeMeta]:
    """Retourne les recettes dont le champ `type` correspond à `type_filter`."""
    return {k: v for k, v in recipes.items() if v.type == type_filter}
```

- [ ] **Step 4 : Vérifier que les tests passent**

```
cd backend && uv run pytest tests/recipes/test_registry.py -v
```
Attendu : tous PASS

- [ ] **Step 5 : Commit**

```bash
git add backend/src/portal/recipes/registry.py backend/tests/recipes/test_registry.py
git commit -m "feat: RecipeRegistry valide les fichiers des recettes start"
```

---

## Task 3 — API recettes : filtre type, création user start, start-recipes workspace

**Files:**
- Modify: `backend/src/portal/routes/recipes.py`
- Modify: `backend/src/portal/routes/workspace_ops.py`
- Modify: `backend/tests/routes/test_recipes.py`
- Modify: `backend/tests/routes/test_workspace_ops.py`

- [ ] **Step 1 : Écrire les tests**

Dans `backend/tests/routes/test_recipes.py`, ajouter (après les imports existants) :

```python
def _make_app_with_start_recipe(tmp_path: Path, login: str = "alice") -> "TestClient":
    """Client avec une recette start dans le répertoire user."""
    import os

    from fastapi.testclient import TestClient
    from fastapi import APIRouter
    from starlette.requests import Request

    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    _write_global_config(tmp_path)

    from portal.app import create_app

    app = create_app()
    test_router = APIRouter()

    @test_router.post("/_test/login")
    async def _login(request: Request):
        request.session["user"] = {"login": login, "roles": ["dev"]}
        return {"ok": True}

    app.include_router(test_router)
    client = TestClient(app)
    client.post("/_test/login")

    # Créer une recette start partagée
    recipe_dir = tmp_path / "recipes" / "claude-rc"
    recipe_dir.mkdir(parents=True, exist_ok=True)
    import yaml

    (recipe_dir / "recipe.meta.yaml").write_text(
        yaml.dump({"id": "claude-rc", "type": "start", "description": "Claude RC"}),
        encoding="utf-8",
    )
    (recipe_dir / "start.sh").write_text(
        "#!/usr/bin/env bash\nexec claude --rc\n", encoding="utf-8"
    )
    return client


def test_get_recipes_type_start_filter(tmp_path: Path, monkeypatch) -> None:
    import os

    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    import portal.routes.recipes as _mod

    _mod._reset_recipe_registry()
    client = _make_app_with_start_recipe(tmp_path)
    resp = client.get("/recipes?type=start")
    assert resp.status_code == 200
    data = resp.json()
    assert all(r["type"] == "start" for r in data)
    assert any(r["id"] == "claude-rc" for r in data)


def test_get_recipes_type_install_excludes_start(tmp_path: Path, monkeypatch) -> None:
    import os

    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    import portal.routes.recipes as _mod

    _mod._reset_recipe_registry()
    client = _make_app_with_start_recipe(tmp_path)
    resp = client.get("/recipes?type=install")
    assert resp.status_code == 200
    data = resp.json()
    assert all(r["id"] != "claude-rc" for r in data)


def test_post_me_start_recipe_creates_recipe(tmp_path: Path, monkeypatch) -> None:
    import os

    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))

    from fastapi.testclient import TestClient
    from fastapi import APIRouter
    from starlette.requests import Request
    import yaml

    _write_global_config(tmp_path)
    # Répertoire user
    user_dir = tmp_path / "users" / "alice"
    user_dir.mkdir(parents=True)
    (user_dir / "config.yaml").write_text(
        yaml.dump({"version": "1", "secret_ns": "00000000-0000-0000-0000-000000000001",
                   "defaults": {}, "harpocrate": {}, "git_credentials": [], "workspaces": []}),
        encoding="utf-8",
    )

    from portal.app import create_app

    app = create_app()
    test_router = APIRouter()

    @test_router.post("/_test/login")
    async def _login(request: Request):
        request.session["user"] = {"login": "alice", "roles": ["dev"]}
        return {"ok": True}

    app.include_router(test_router)
    client = TestClient(app)
    client.post("/_test/login")

    resp = client.post(
        "/me/start-recipes",
        json={"id": "my-start", "description": "Mon script", "script": "#!/bin/bash\necho ok\n"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "my-start"
    assert data["type"] == "start"

    # Vérifier que les fichiers existent
    recipe_path = tmp_path / "users" / "alice" / "recipes" / "my-start"
    assert (recipe_path / "recipe.meta.yaml").exists()
    assert (recipe_path / "start.sh").exists()


def test_post_me_start_recipe_invalid_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    _write_global_config(tmp_path)

    from fastapi.testclient import TestClient
    from fastapi import APIRouter
    from starlette.requests import Request

    from portal.app import create_app

    app = create_app()
    test_router = APIRouter()

    @test_router.post("/_test/login")
    async def _login(request: Request):
        request.session["user"] = {"login": "alice", "roles": ["dev"]}
        return {"ok": True}

    app.include_router(test_router)
    client = TestClient(app)
    client.post("/_test/login")
    resp = client.post(
        "/me/start-recipes",
        json={"id": "INVALID NAME!", "script": "echo ok"},
    )
    assert resp.status_code == 422
```

Dans `backend/tests/routes/test_workspace_ops.py`, ajouter :

```python
def test_get_workspace_start_recipes_returns_list(tmp_path, monkeypatch, client):
    """GET /workspaces/{name}/start-recipes retourne les start recipes attachées."""
    import yaml
    from unittest.mock import patch

    login = "alice"
    ws_name = "my-ws"
    ws_id = f"{login}-{ws_name}"

    # Préparer la config workspace avec start_recipes
    user_dir = tmp_path / "users" / login
    user_dir.mkdir(parents=True, exist_ok=True)
    ws_spec = {
        "name": ws_name,
        "source": "https://github.com/x/y",
        "start_recipes": ["claude-rc"],
    }
    user_cfg = {
        "version": "1",
        "secret_ns": "00000000-0000-0000-0000-000000000001",
        "defaults": {}, "harpocrate": {}, "git_credentials": [],
        "workspaces": [ws_spec],
    }
    (user_dir / "config.yaml").write_text(yaml.dump(user_cfg), encoding="utf-8")

    # Préparer la recette claude-rc partagée
    recipe_dir = tmp_path / "recipes" / "claude-rc"
    recipe_dir.mkdir(parents=True, exist_ok=True)
    (recipe_dir / "recipe.meta.yaml").write_text(
        yaml.dump({"id": "claude-rc", "type": "start", "description": "Claude RC"}),
        encoding="utf-8",
    )
    (recipe_dir / "start.sh").write_text("#!/bin/bash\nexec claude --rc\n", encoding="utf-8")

    resp = client.get(f"/me/workspaces/{ws_name}/start-recipes")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(r["id"] == "claude-rc" for r in data)
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```
cd backend && uv run pytest tests/routes/test_recipes.py::test_get_recipes_type_start_filter tests/routes/test_workspace_ops.py::test_get_workspace_start_recipes_returns_list -v
```
Attendu : FAIL

- [ ] **Step 3 : Implémenter le filtre `?type=` dans `GET /recipes`**

Dans `backend/src/portal/routes/recipes.py`, modifier `list_recipes` :

```python
from fastapi import APIRouter, Depends, HTTPException, Query   # ajouter Query
from ..recipes.registry import RecipeRegistry

# Ajouter une fonction reset pour les tests (après les routeurs globaux) :
_registry_cache: RecipeRegistry | None = None

def _reset_recipe_registry() -> None:
    global _registry_cache
    _registry_cache = None


@router_public.get("/recipes")
async def list_recipes(
    user: UserInfo = Depends(require_user),
    recipe_type: str | None = Query(default=None, alias="type"),
) -> list[dict[str, Any]]:
    """Liste les recettes partagées + personnelles. Filtre optionnel: ?type=start|install"""
    data_root = _data_root()
    shared_dir = data_root / "recipes"
    personal_dir = safe_user_path(user.login, "recipes")
    registry = RecipeRegistry(builtin_dir=None, shared_dir=shared_dir)
    shared = registry.load_shared()
    personal = registry.load_dir(personal_dir)
    available = {**shared, **personal}
    if recipe_type and recipe_type in ("start", "install"):
        available = RecipeRegistry.filter_by_type(available, recipe_type)
    return [m.model_dump() for m in available.values()]
```

- [ ] **Step 4 : Implémenter `POST /me/start-recipes`**

Dans `backend/src/portal/routes/recipes.py`, ajouter après `router_me.delete` :

```python
class StartRecipeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: str = "1.0.0"
    description: str = ""
    script: str = "#!/usr/bin/env bash\nset -euo pipefail\n"

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not _RECIPE_ID_RE.fullmatch(v):
            raise ValueError(f"id {v!r} must match ^[a-z0-9]([a-z0-9-]{{0,38}}[a-z0-9])?$")
        return v


@router_me.post("/start-recipes", status_code=201)
async def create_personal_start_recipe(
    body: StartRecipeCreateRequest,
    user: UserInfo = Depends(require_user),
) -> dict[str, Any]:
    """Crée une recette start personnelle (start.sh dans le répertoire user)."""
    personal_dir = safe_user_path(user.login, "recipes")
    recipe_path = personal_dir / body.id
    try:
        if not recipe_path.is_relative_to(personal_dir):
            raise HTTPException(status_code=422, detail="Path traversal detected")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid recipe path") from exc

    if recipe_path.exists():
        raise HTTPException(status_code=409, detail=f"Recipe {body.id!r} already exists")

    from ..recipes.models import RecipeMeta

    meta = RecipeMeta(id=body.id, version=body.version, description=body.description, type="start")

    def _write() -> None:
        tmp = personal_dir / f".tmp-{body.id}"
        try:
            tmp.mkdir(parents=True, exist_ok=False)
            (tmp / "recipe.meta.yaml").write_text(
                yaml.dump(meta.model_dump(), default_flow_style=False), encoding="utf-8"
            )
            start_sh = tmp / "start.sh"
            start_sh.write_text(body.script, encoding="utf-8")
            start_sh.chmod(0o755)
            tmp.rename(recipe_path)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise

    await asyncio.to_thread(_write)
    _log.info("personal_start_recipe_created", recipe_id=body.id, by=user.login)
    return meta.model_dump()
```

- [ ] **Step 5 : Implémenter `GET /workspaces/{name}/start-recipes`**

Dans `backend/src/portal/routes/workspace_ops.py`, ajouter avant la dernière route :

```python
@router.get("/workspaces/{name}/start-recipes")
async def get_workspace_start_recipes(
    name: str,
    user: UserInfo = Depends(require_user),
) -> list[dict[str, Any]]:
    """Retourne les start recipes attachées au workspace avec leurs métadonnées."""
    _validate_name(name)
    cfg = await asyncio.to_thread(
        lambda: next(
            (ws for ws in __import__("portal.config.store", fromlist=["load_user"])
             .load_user(user.login).workspaces if ws.name == name),
            None,
        )
    )
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Workspace {name!r} not found")

    if not cfg.start_recipes:
        return []

    reg = _get_recipe_registry()
    shared = await asyncio.to_thread(reg.load_shared)
    personal_dir = safe_user_path(user.login, "recipes")
    personal = await asyncio.to_thread(reg.load_dir, personal_dir)
    available = {**shared, **personal}

    result = []
    for rid in cfg.start_recipes:
        if rid in available:
            result.append(available[rid].model_dump())
    return result
```

**Note :** L'import inline évite le cycle d'imports. L'alternative propre est d'importer `load_user` en tête de fichier comme les autres imports (cf. la fonction `_resolve_feature_secrets` dans le même fichier qui fait aussi des imports locaux).

Remplacer le lambda ci-dessus par ce pattern propre :

```python
@router.get("/workspaces/{name}/start-recipes")
async def get_workspace_start_recipes(
    name: str,
    user: UserInfo = Depends(require_user),
) -> list[dict[str, Any]]:
    """Retourne les start recipes attachées au workspace avec leurs métadonnées."""
    _validate_name(name)

    from ..config.store import load_user

    user_cfg = await asyncio.to_thread(load_user, user.login)
    ws_spec = next((ws for ws in user_cfg.workspaces if ws.name == name), None)
    if ws_spec is None:
        raise HTTPException(status_code=404, detail=f"Workspace {name!r} not found")
    if not ws_spec.start_recipes:
        return []

    reg = _get_recipe_registry()
    shared = await asyncio.to_thread(reg.load_shared)
    personal_dir = safe_user_path(user.login, "recipes")
    personal = await asyncio.to_thread(reg.load_dir, personal_dir)
    available = {**shared, **personal}

    return [available[rid].model_dump() for rid in ws_spec.start_recipes if rid in available]
```

- [ ] **Step 6 : Vérifier que tous les tests passent**

```
cd backend && uv run pytest tests/routes/test_recipes.py tests/routes/test_workspace_ops.py -v
```
Attendu : tous PASS

- [ ] **Step 7 : Commit**

```bash
git add backend/src/portal/routes/recipes.py backend/src/portal/routes/workspace_ops.py backend/tests/routes/test_recipes.py backend/tests/routes/test_workspace_ops.py
git commit -m "feat: filtre /recipes?type=, POST /me/start-recipes, GET /workspaces/{name}/start-recipes"
```

---

## Task 4 — Route WebSocket `/workspaces/{name}/ssh`

**Files:**
- Create: `backend/src/portal/routes/workspace_ssh.py`
- Modify: `backend/src/portal/app.py`

- [ ] **Step 1 : Créer `workspace_ssh.py`**

```python
# backend/src/portal/routes/workspace_ssh.py
from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import shlex
from pathlib import Path
from urllib.parse import urlparse

import structlog
from fastapi import APIRouter
from starlette.websockets import WebSocketDisconnect

from ..config.store import _data_root, load_global, load_user, safe_user_path
from ..recipes.registry import RecipeRegistry
from ..settings import get_settings

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["workspace-ssh"])

_SESSION_ID_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]?$")


@router.websocket("/workspaces/{name}/ssh")
async def workspace_ssh_terminal(
    name: str,
    websocket,
    start: str | None = None,
) -> None:
    await websocket.accept()
    settings = get_settings()
    cfg = load_global()

    # ── Origin validation (anti-CSWSH) ────────────────────────────────────────
    if not settings.dev_mode:
        parsed = urlparse(cfg.server.external_url)
        allowed_origin = f"{parsed.scheme}://{parsed.netloc}"
        request_origin = websocket.headers.get("origin", "").rstrip("/")
        if request_origin != allowed_origin:
            _log.warning("ws_workspace_ssh_bad_origin", origin=request_origin)
            await websocket.close(code=4003, reason="Bad origin")
            return

    # ── Auth ──────────────────────────────────────────────────────────────────
    user_data = websocket.session.get("user")
    if not user_data or not isinstance(user_data, dict):
        await websocket.close(code=4001, reason="Not authenticated")
        return
    login: str = user_data.get("login", "")
    if not login:
        await websocket.close(code=4001, reason="Invalid session")
        return

    # ── Validation du workspace ────────────────────────────────────────────────
    from ..recipes.models import _RECIPE_ID_RE

    if not __import__("re").compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$").fullmatch(name):
        await websocket.close(code=4022, reason="Invalid workspace name")
        return

    ws_id = f"{login}-{name}"

    # ── Résolution de la start recipe (si fournie) ────────────────────────────
    tmux_cmd: str
    if start is not None:
        if not _RECIPE_ID_RE.fullmatch(start):
            await websocket.close(code=4022, reason=f"Invalid start recipe id {start!r}")
            return

        data_root = _data_root()
        shared_dir = data_root / "recipes"
        personal_dir = safe_user_path(login, "recipes")
        registry = RecipeRegistry(builtin_dir=None, shared_dir=shared_dir)
        shared = registry.load_shared()
        personal = registry.load_dir(personal_dir)
        available = {**shared, **personal}

        recipe = available.get(start)
        if recipe is None or recipe.type != "start":
            await websocket.close(code=4022, reason=f"Start recipe {start!r} not found")
            return

        # Lire start.sh depuis le répertoire de la recette
        recipe_dir = personal_dir / start if (personal_dir / start).exists() else shared_dir / start
        start_sh_path = recipe_dir / "start.sh"
        if not start_sh_path.exists():
            await websocket.close(code=4022, reason=f"start.sh missing for {start!r}")
            return

        script_content = start_sh_path.read_text(encoding="utf-8")
        b64 = base64.b64encode(script_content.encode()).decode()
        session_name = start
        tmux_cmd = f"tmux new -A -s {session_name} -- bash -lc \"$(echo {b64} | base64 -d)\""
    else:
        tmux_cmd = "tmux new -A -s main"

    # ── Build commande devpod ssh ─────────────────────────────────────────────
    devpod_bin = shlex.split(cfg.devpod.binary, posix=(os.name != "nt"))
    cmd = [*devpod_bin, "ssh", ws_id, "--command", tmux_cmd]

    _log.info("ws_workspace_ssh_open", ws_id=ws_id, login=login, start=start)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    async def _ws_to_ssh() -> None:
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                raw: bytes | None = message.get("bytes")
                if raw is None:
                    raw = (message.get("text") or "").encode()
                if raw and proc.stdin and not proc.stdin.is_closing():
                    proc.stdin.write(raw)
                    await proc.stdin.drain()
        except (WebSocketDisconnect, OSError):
            pass
        except Exception as exc:
            _log.warning("ws_workspace_ssh_ws_to_ssh_error", exc_type=type(exc).__name__)

    async def _ssh_to_ws() -> None:
        try:
            if proc.stdout is None:
                return
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                await websocket.send_bytes(chunk)
        except (WebSocketDisconnect, OSError):
            pass
        except Exception as exc:
            _log.warning("ws_workspace_ssh_ssh_to_ws_error", exc_type=type(exc).__name__)

    tasks = [
        asyncio.create_task(_ws_to_ssh()),
        asyncio.create_task(_ssh_to_ws()),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        with contextlib.suppress(Exception):
            await websocket.close()

    _log.info("ws_workspace_ssh_closed", ws_id=ws_id, returncode=proc.returncode)
```

- [ ] **Step 2 : Enregistrer le router dans `app.py`**

Dans `backend/src/portal/app.py`, ajouter :

```python
from .routes.workspace_ssh import router as workspace_ssh_router
```

Puis dans `create_app()`, après `app.include_router(workspace_ops_router, prefix="/me")` :

```python
app.include_router(workspace_ssh_router, prefix="/me")
```

- [ ] **Step 3 : Vérifier les imports (pas de test encore)**

```
cd backend && uv run python -c "from portal.app import create_app; create_app()"
```
Attendu : pas d'erreur d'import

- [ ] **Step 4 : Commit**

```bash
git add backend/src/portal/routes/workspace_ssh.py backend/src/portal/app.py
git commit -m "feat: route WebSocket /me/workspaces/{name}/ssh avec tmux + start recipes"
```

---

## Task 5 — Tests de la route WebSocket workspace SSH

**Files:**
- Create: `backend/tests/routes/test_workspace_ssh.py`

- [ ] **Step 1 : Créer le fichier de tests**

```python
# backend/tests/routes/test_workspace_ssh.py
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml
from fastapi import APIRouter
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.websockets import WebSocketDisconnect


BASE_CONFIG = {
    "version": "1",
    "server": {
        "listen": "0.0.0.0:8080",
        "base_domain": "dev.yoops.org",
        "external_url": "https://dev.yoops.org",
        "dev_mode": True,
        "log": {"level": "info", "format": "text", "output": ""},
    },
    "auth": {
        "oidc": {
            "issuer": "https://kc.test",
            "client_id": "portal",
            "client_secret": "",
            "scopes": ["openid"],
            "role_claim": "realm_access.roles",
            "admin_role": "admin",
            "user_role": "dev",
            "username_claim": "preferred_username",
        }
    },
    "secrets": {"backend": "inline", "harpocrate": {"url": "", "api_key": "", "base_path": "devpod"}},
    "devpod": {
        "binary": "devpod",
        "defaults": {"ide": "openvscode", "idle_timeout": "2h", "dotfiles": ""},
        "client_cert_path": "/data/certs/portal",
    },
    "hosts": [],
    "caddy": {"admin_api": ""},
    "cloudflare_manager": {"url": "", "api_key": ""},
}


def _make_client(tmp_path: Path, monkeypatch, login: str = "alice") -> TestClient:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "true")
    import portal.settings as mod

    mod._settings = None
    (tmp_path / "config.yaml").write_text(yaml.dump(BASE_CONFIG), encoding="utf-8")

    from portal.app import create_app

    app = create_app()
    test_router = APIRouter()

    @test_router.post("/_test/login")
    async def _login(request: Request):
        request.session["user"] = {"login": login, "roles": ["dev"]}
        return {"ok": True}

    app.include_router(test_router)
    client = TestClient(app)
    client.post("/_test/login")
    return client


def _write_start_recipe(data_root: Path, recipe_id: str, scope: str = "shared", login: str = "alice") -> None:
    if scope == "shared":
        recipe_dir = data_root / "recipes" / recipe_id
    else:
        recipe_dir = data_root / "users" / login / "recipes" / recipe_id
    recipe_dir.mkdir(parents=True, exist_ok=True)
    (recipe_dir / "recipe.meta.yaml").write_text(
        yaml.dump({"id": recipe_id, "type": "start", "description": "test"}), encoding="utf-8"
    )
    (recipe_dir / "start.sh").write_text(
        f"#!/usr/bin/env bash\nexec {recipe_id}\n", encoding="utf-8"
    )


def _assert_ws_closes_with(client: TestClient, path: str, expected_code: int) -> None:
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(path) as ws:
        ws.receive_text()
    assert exc_info.value.code == expected_code


# ── Tests d'authentification ──────────────────────────────────────────────────


def test_ws_workspace_ssh_rejects_unauthenticated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "true")
    import portal.settings as mod

    mod._settings = None
    (tmp_path / "config.yaml").write_text(yaml.dump(BASE_CONFIG), encoding="utf-8")

    from portal.app import create_app

    client = TestClient(create_app())
    _assert_ws_closes_with(client, "/me/workspaces/my-ws/ssh", 4001)


# ── Tests de validation ────────────────────────────────────────────────────────


def test_ws_workspace_ssh_rejects_invalid_workspace_name(tmp_path: Path, monkeypatch) -> None:
    client = _make_client(tmp_path, monkeypatch)
    _assert_ws_closes_with(client, "/me/workspaces/INVALID!/ssh", 4022)


def test_ws_workspace_ssh_rejects_unknown_start_recipe(tmp_path: Path, monkeypatch) -> None:
    client = _make_client(tmp_path, monkeypatch)
    _assert_ws_closes_with(client, "/me/workspaces/my-ws/ssh?start=unknown-recipe", 4022)


def test_ws_workspace_ssh_rejects_start_recipe_wrong_type(tmp_path: Path, monkeypatch) -> None:
    """Une recette de type install ne peut pas être utilisée comme start recipe."""
    import json as _json

    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "true")
    import portal.settings as mod

    mod._settings = None
    (tmp_path / "config.yaml").write_text(yaml.dump(BASE_CONFIG), encoding="utf-8")

    install_dir = tmp_path / "recipes" / "my-install"
    install_dir.mkdir(parents=True, exist_ok=True)
    (install_dir / "recipe.meta.yaml").write_text(
        yaml.dump({"id": "my-install", "type": "install"}), encoding="utf-8"
    )
    (install_dir / "devcontainer-feature.json").write_text(
        _json.dumps({"id": "my-install", "version": "1.0.0"}), encoding="utf-8"
    )
    (install_dir / "install.sh").write_text("#!/bin/bash\necho ok\n", encoding="utf-8")

    from portal.app import create_app
    from fastapi import APIRouter
    from starlette.requests import Request

    app = create_app()
    test_router = APIRouter()

    @test_router.post("/_test/login")
    async def _login(request: Request):
        request.session["user"] = {"login": "alice", "roles": ["dev"]}
        return {"ok": True}

    app.include_router(test_router)
    client = TestClient(app)
    client.post("/_test/login")
    _assert_ws_closes_with(client, "/me/workspaces/my-ws/ssh?start=my-install", 4022)


# ── Tests proxy nominal ────────────────────────────────────────────────────────


class _FakeProcess:
    def __init__(self, echo: bool = True) -> None:
        self.returncode: int | None = None
        self._killed = False
        self._echo = echo
        self.stdin = _FakeStdin(self)
        self.stdout = _FakeStdout()

    def kill(self) -> None:
        self._killed = True
        self.returncode = -9
        self.stdout._close()

    async def wait(self) -> int:
        return self.returncode or 0


class _FakeStdin:
    def __init__(self, proc: _FakeProcess) -> None:
        self._proc = proc

    def is_closing(self) -> bool:
        return self._proc.returncode is not None

    def write(self, data: bytes) -> None:
        if self._proc._echo:
            self._proc.stdout._feed(data)

    async def drain(self) -> None:
        pass


class _FakeStdout:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._closed = False

    def _feed(self, data: bytes) -> None:
        self._queue.put_nowait(data)

    def _close(self) -> None:
        self._closed = True
        self._queue.put_nowait(b"")

    async def read(self, n: int) -> bytes:
        if self._closed and self._queue.empty():
            return b""
        return await self._queue.get()


def test_ws_workspace_ssh_no_start_uses_tmux_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sans ?start, la commande doit utiliser 'tmux new -A -s main'."""
    captured: list[list[str]] = []

    async def _fake_exec(*args: object, **kwargs: object) -> _FakeProcess:
        captured.append(list(args))
        return _FakeProcess(echo=False)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    client = _make_client(tmp_path, monkeypatch)

    with client.websocket_connect("/me/workspaces/my-ws/ssh"):
        pass

    assert captured, "create_subprocess_exec doit avoir été appelé"
    cmd = captured[0]
    assert "ssh" in cmd
    assert "alice-my-ws" in cmd
    assert "--command" in cmd
    command_str = cmd[cmd.index("--command") + 1]
    assert "tmux new -A -s main" in command_str
    assert "base64" not in command_str  # pas de script encodé pour la session nue


def test_ws_workspace_ssh_with_start_encodes_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Avec ?start=claude-rc, start.sh est encodé en base64 dans la commande."""
    import base64

    _write_start_recipe(tmp_path, "claude-rc")
    captured: list[list[str]] = []

    async def _fake_exec(*args: object, **kwargs: object) -> _FakeProcess:
        captured.append(list(args))
        return _FakeProcess(echo=False)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    client = _make_client(tmp_path, monkeypatch)

    with client.websocket_connect("/me/workspaces/my-ws/ssh?start=claude-rc"):
        pass

    assert captured
    cmd = captured[0]
    assert "--command" in cmd
    command_str = cmd[cmd.index("--command") + 1]
    assert "base64" in command_str
    assert "tmux new -A -s claude-rc" in command_str
    # Décoder le b64 et vérifier que c'est bien le script
    import re as _re

    match = _re.search(r"echo ([A-Za-z0-9+/=]+) \| base64 -d", command_str)
    assert match, "La commande doit contenir un bloc base64"
    decoded = base64.b64decode(match.group(1)).decode()
    assert "exec claude-rc" in decoded


def test_ws_workspace_ssh_origin_rejected_non_dev(tmp_path: Path, monkeypatch) -> None:
    """En mode non-dev, un mauvais Origin est rejeté (4003)."""
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "false")
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-secret")
    import portal.settings as mod

    mod._settings = None
    cfg = dict(BASE_CONFIG)
    cfg["server"] = dict(cfg["server"])
    cfg["server"]["dev_mode"] = False
    (tmp_path / "config.yaml").write_text(yaml.dump(cfg), encoding="utf-8")

    from portal.app import create_app
    from fastapi import APIRouter
    from starlette.requests import Request

    app = create_app()
    test_router = APIRouter()

    @test_router.post("/_test/login")
    async def _login(request: Request):
        request.session["user"] = {"login": "alice", "roles": ["dev"]}
        return {"ok": True}

    app.include_router(test_router)
    client = TestClient(app)
    client.post("/_test/login")

    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(
            "/me/workspaces/my-ws/ssh",
            headers={"Origin": "https://evil.example.com"},
        ) as ws,
    ):
        ws.receive_text()
    assert exc_info.value.code == 4003
```

- [ ] **Step 2 : Lancer les tests**

```
cd backend && uv run pytest tests/routes/test_workspace_ssh.py -v
```
Attendu : tous PASS

- [ ] **Step 3 : Commit**

```bash
git add backend/tests/routes/test_workspace_ssh.py
git commit -m "test: route WebSocket /workspaces/{name}/ssh — auth, validation, proxy"
```

---

## Task 6 — Frontend : types, hooks, `useWorkspaceOps`

**Files:**
- Modify: `frontend/src/features/workspaces/types.ts`
- Create: `frontend/src/features/workspaces/useStartRecipes.ts`
- Modify: `frontend/src/features/workspaces/useWorkspaceOps.ts`

- [ ] **Step 1 : Mettre à jour `types.ts`**

Dans `frontend/src/features/workspaces/types.ts`, modifier `WorkspaceSpec` :

```typescript
export interface WorkspaceSpec {
  name: string
  source: string
  branch: string
  git_credential: string
  host: string
  recipes: string[]
  env: Record<string, string>
  extra_sources: SourceSpec[]
  ssh_key?: boolean
  profile?: { scope: 'shared' | 'user'; slug: string } | null
  start_recipes?: string[]
  default_start?: string
}
```

- [ ] **Step 2 : Créer `useStartRecipes.ts`**

```typescript
// frontend/src/features/workspaces/useStartRecipes.ts
import { useQuery } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'

export interface StartRecipe {
  id: string
  version: string
  description: string
  type: 'start'
}

export function useStartRecipes() {
  return useQuery<StartRecipe[]>({
    queryKey: ['recipes', 'start'],
    queryFn: () => apiFetchJson<StartRecipe[]>('/recipes?type=start'),
    staleTime: 10 * 60 * 1000,
  })
}
```

- [ ] **Step 3 : Mettre à jour `useWorkspaceOps.ts`**

Ajouter `startRecipes` à `CreateInput` et l'inclure dans la spec envoyée :

```typescript
interface CreateInput {
  name: string
  sources: SourceEntry[]
  host: string
  recipes: string[]
  generateSshKey?: boolean
  profile?: { scope: 'shared' | 'user'; slug: string }
  startRecipes?: string[]       // ← nouveau
  defaultStart?: string         // ← nouveau
}
```

Dans `mutationFn`, modifier la construction de `spec` :

```typescript
const spec: WorkspaceSpec = {
  name,
  source: primary.url,
  branch: primary.branch,
  git_credential: primary.credential,
  host,
  recipes,
  env: {},
  extra_sources: extra,
  ssh_key: generateSshKey ?? false,
  profile: profile ?? null,
  start_recipes: startRecipes ?? [],          // ← nouveau
  default_start: defaultStart ?? '',          // ← nouveau
}
```

- [ ] **Step 4 : Vérifier TypeScript**

```
cd frontend && npx tsc --noEmit
```
Attendu : pas d'erreur

- [ ] **Step 5 : Commit**

```bash
git add frontend/src/features/workspaces/types.ts frontend/src/features/workspaces/useStartRecipes.ts frontend/src/features/workspaces/useWorkspaceOps.ts
git commit -m "feat: types WorkspaceSpec.start_recipes + useStartRecipes hook"
```

---

## Task 7 — Frontend : `WorkspaceSshTerminalWindow`

**Files:**
- Create: `frontend/src/features/workspaces/WorkspaceSshTerminalWindow.tsx`

- [ ] **Step 1 : Créer le composant**

Même structure que `SshTerminalWindow` (admin) mais URL différente et props adaptées :

```typescript
// frontend/src/features/workspaces/WorkspaceSshTerminalWindow.tsx
import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'

interface Props {
  wsName: string
  startId?: string   // undefined = shell nu
  onClose: () => void
}

export default function WorkspaceSshTerminalWindow({ wsName, startId, onClose }: Props) {
  const { t } = useTranslation()
  const termRef = useRef<HTMLDivElement>(null)
  const posRef = useRef({ x: Math.max(0, window.innerWidth - 640), y: 80 })
  const winRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)
  const dragOrigin = useRef({ mx: 0, my: 0, wx: 0, wy: 0 })
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    const terminal = new Terminal({
      cursorBlink: true,
      fontFamily: "'Courier New', monospace",
      fontSize: 13,
      theme: { background: '#0d0d1a', foreground: '#e0e0ff', cursor: '#e0e0ff' },
    })
    const fitAddon = new FitAddon()
    terminal.loadAddon(fitAddon)

    if (termRef.current) {
      terminal.open(termRef.current)
      fitAddon.fit()
      terminal.focus()
    }

    const onResize = () => fitAddon.fit()
    window.addEventListener('resize', onResize)
    const ro = new ResizeObserver(() => fitAddon.fit())
    if (winRef.current) ro.observe(winRef.current)

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const query = startId ? `?start=${encodeURIComponent(startId)}` : ''
    const ws = new WebSocket(
      `${proto}//${window.location.host}/me/workspaces/${encodeURIComponent(wsName)}/ssh${query}`
    )
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    const encoder = new TextEncoder()
    const dataDisposable = terminal.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(encoder.encode(data))
    })

    ws.onmessage = (e) => {
      const data = e.data instanceof ArrayBuffer ? new Uint8Array(e.data) : e.data
      terminal.write(data)
    }
    ws.onclose = () => terminal.write(t('admin.sshTerminal.connClosed'))
    ws.onerror = () => terminal.write(t('admin.sshTerminal.connError'))

    return () => {
      window.removeEventListener('resize', onResize)
      ro.disconnect()
      dataDisposable.dispose()
      ws.close()
      terminal.dispose()
      wsRef.current = null
    }
  }, [wsName, startId, t])

  useEffect(() => {
    function onMove(e: MouseEvent) {
      if (!dragging.current || !winRef.current) return
      posRef.current = {
        x: dragOrigin.current.wx + e.clientX - dragOrigin.current.mx,
        y: dragOrigin.current.wy + e.clientY - dragOrigin.current.my,
      }
      winRef.current.style.left = `${posRef.current.x}px`
      winRef.current.style.top = `${posRef.current.y}px`
    }
    function onUp() { dragging.current = false }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
    return () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
  }, [])

  function handleHeaderMouseDown(e: React.MouseEvent) {
    if ((e.target as HTMLElement).tagName === 'BUTTON') return
    dragging.current = true
    dragOrigin.current = { mx: e.clientX, my: e.clientY, wx: posRef.current.x, wy: posRef.current.y }
    e.preventDefault()
  }

  function handleClose() {
    wsRef.current?.close()
    onClose()
  }

  const sessionLabel = startId ?? t('workspaces.ssh.shell')

  const window_ = (
    <div
      ref={winRef}
      style={{
        position: 'fixed',
        left: posRef.current.x,
        top: posRef.current.y,
        width: 600,
        height: 440,
        minWidth: 360,
        minHeight: 240,
        zIndex: 9999,
        borderRadius: 8,
        overflow: 'hidden',
        boxShadow: '0 8px 32px rgba(0,0,0,0.45)',
        display: 'flex',
        flexDirection: 'column',
        resize: 'both',
      }}
    >
      <div
        onMouseDown={handleHeaderMouseDown}
        style={{
          background: '#2d2d3f',
          padding: '8px 12px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'grab',
          userSelect: 'none',
          flexShrink: 0,
        }}
      >
        <span style={{ fontSize: 12, color: '#a0a0c0', fontFamily: 'monospace' }}>
          ⚡ {sessionLabel} — {wsName}
        </span>
        <button
          onClick={handleClose}
          aria-label={t('workspaces.ssh.closeLabel')}
          style={{
            width: 13, height: 13, borderRadius: '50%',
            background: '#ef4444', border: 'none', cursor: 'pointer', display: 'block',
          }}
        />
      </div>
      <div ref={termRef} style={{ flex: 1, minHeight: 0, background: '#0d0d1a', padding: '4px 2px' }} />
    </div>
  )

  return createPortal(window_, document.body)
}
```

- [ ] **Step 2 : Vérifier TypeScript**

```
cd frontend && npx tsc --noEmit
```
Attendu : pas d'erreur

- [ ] **Step 3 : Commit**

```bash
git add frontend/src/features/workspaces/WorkspaceSshTerminalWindow.tsx
git commit -m "feat: WorkspaceSshTerminalWindow — terminal SSH flottant pour workspaces"
```

---

## Task 8 — Frontend : `WorkspaceCard` — Open VSCode + SSH session menu

**Files:**
- Modify: `frontend/src/features/workspaces/WorkspaceCard.tsx`

- [ ] **Step 1 : Implémenter les changements**

Lire le fichier actuel. Les changements :
1. Ajouter `DropdownMenu` imports depuis `@/components/ui/dropdown-menu`
2. Importer `WorkspaceSshTerminalWindow`
3. Ajouter `sshOpen` + `sshStartId` state
4. Renommer "Open" → "Open VSCode"
5. Ajouter le bouton SSH (ou menu dropdown)
6. Ajouter `WorkspaceSshTerminalWindow` conditionnel en fin de JSX

Vérifier si shadcn/ui dispose de `DropdownMenu` :

```
ls frontend/src/components/ui/dropdown-menu.tsx 2>/dev/null || echo "absent"
```

Si absent, utiliser un simple `<select>` natif ou une liste de boutons directement (shadcn Select).

**Version complète de `WorkspaceCard.tsx` avec SSH :**

Ajouter en tête des imports :

```typescript
import { useState } from 'react'
import WorkspaceSshTerminalWindow from './WorkspaceSshTerminalWindow'
```

Ajouter au state :

```typescript
const [sshOpen, setSshOpen] = useState(false)
const [sshStartId, setSshStartId] = useState<string | undefined>(undefined)

function openSsh(startId?: string) {
  setSshStartId(startId)
  setSshOpen(true)
}
```

Modifier le bouton "Open" :

```tsx
{s === 'running' && status.url && (
  <Button size="sm" asChild>
    <a href={status.url} target="_blank" rel="noopener noreferrer">
      {t('workspaces.actions.openVscode')}
    </a>
  </Button>
)}
```

Ajouter le bouton SSH (après le bouton "Stop") :

```tsx
{s === 'running' && (
  <>
    {spec.start_recipes && spec.start_recipes.length > 0 ? (
      /* Dropdown avec start recipes + Shell */
      <div className="relative">
        <select
          className="h-8 rounded-md border border-input bg-background px-2 text-xs"
          defaultValue=""
          onChange={(e) => {
            if (e.target.value === '') return
            if (e.target.value === '__shell__') {
              openSsh(undefined)
            } else {
              openSsh(e.target.value)
            }
            e.target.value = ''
          }}
        >
          <option value="" disabled>{t('workspaces.ssh.newSession')}</option>
          {spec.start_recipes.map((rid) => (
            <option key={rid} value={rid}>{rid}</option>
          ))}
          <option value="__shell__">{t('workspaces.ssh.shell')}</option>
        </select>
      </div>
    ) : (
      <Button size="sm" variant="outline" onClick={() => openSsh(undefined)}>
        {t('workspaces.ssh.shell')}
      </Button>
    )}
  </>
)}
```

Ajouter en fin de JSX (avant la fermeture de `<div className="rounded-lg border bg-card p-4">`) :

```tsx
{sshOpen && (
  <WorkspaceSshTerminalWindow
    wsName={spec.name}
    startId={sshStartId}
    onClose={() => setSshOpen(false)}
  />
)}
```

Aussi, ajouter `start_recipes?: string[]` aux Props si `spec` n'est pas encore typé avec ce champ (il est dans WorkspaceSpec, pas besoin de redéclarer).

- [ ] **Step 2 : Vérifier TypeScript**

```
cd frontend && npx tsc --noEmit
```
Attendu : pas d'erreur

- [ ] **Step 3 : Commit**

```bash
git add frontend/src/features/workspaces/WorkspaceCard.tsx
git commit -m "feat: WorkspaceCard — renommer Open→Open VSCode, ajouter SSH session"
```

---

## Task 9 — Frontend : `WorkspaceCreate` + i18n

**Files:**
- Modify: `frontend/src/features/workspaces/WorkspaceCreate.tsx`
- Modify: `frontend/src/i18n/en.json`
- Modify: `frontend/src/i18n/fr.json`

- [ ] **Step 1 : Ajouter i18n**

Dans `frontend/src/i18n/en.json`, dans `"workspaces"` :

```json
"actions": {
  "open": "Open",
  "openVscode": "Open VSCode",
  "stop": "Stop",
  "start": "Start",
  "delete": "Delete",
  "retry": "Retry",
  "edit": "Edit"
},
"ssh": {
  "newSession": "New SSH session",
  "shell": "Shell",
  "closeLabel": "Close SSH session"
},
"form": {
  ...existing fields...,
  "startRecipes": "Start recipes",
  "addStartRecipe": "Add start recipe",
  "newStartRecipe": "New start recipe",
  "startRecipeId": "Recipe ID",
  "startRecipeScript": "Script (start.sh)",
  "startRecipeIdHint": "Lowercase letters, numbers, hyphens — 2 to 32 chars",
  "startRecipeScriptDefault": "#!/usr/bin/env bash\nset -euo pipefail\n",
  "startRecipeCreated": "Start recipe \"{{id}}\" created."
}
```

Dans `frontend/src/i18n/fr.json`, dans `"workspaces"` :

```json
"actions": {
  "open": "Ouvrir",
  "openVscode": "Ouvrir VSCode",
  "stop": "Arrêter",
  "start": "Démarrer",
  "delete": "Supprimer",
  "retry": "Réessayer",
  "edit": "Modifier"
},
"ssh": {
  "newSession": "Nouvelle session SSH",
  "shell": "Shell",
  "closeLabel": "Fermer la session SSH"
},
"form": {
  ...champs existants...,
  "startRecipes": "Recettes start",
  "addStartRecipe": "Ajouter une recette start",
  "newStartRecipe": "Nouvelle recette start",
  "startRecipeId": "ID de la recette",
  "startRecipeScript": "Script (start.sh)",
  "startRecipeIdHint": "Minuscules, chiffres, tirets — 2 à 32 caractères",
  "startRecipeScriptDefault": "#!/usr/bin/env bash\nset -euo pipefail\n",
  "startRecipeCreated": "Recette start «{{id}}» créée."
}
```

- [ ] **Step 2 : Mettre à jour `WorkspaceCreate.tsx`**

Ajouter les imports :

```typescript
import { toast } from 'sonner'
import { useStartRecipes } from './useStartRecipes'
import { apiFetchJson } from '@/shared/api/client'
```

Ajouter le state :

```typescript
const { data: startRecipes = [] } = useStartRecipes()
const [selectedStartRecipes, setSelectedStartRecipes] = useState<string[]>([])
const [showNewStart, setShowNewStart] = useState(false)
const [newStartId, setNewStartId] = useState('')
const [newStartScript, setNewStartScript] = useState(t('workspaces.form.startRecipeScriptDefault'))
const [newStartSaving, setNewStartSaving] = useState(false)
```

Modifier l'appel à `createWorkspace.mutateAsync` :

```typescript
await createWorkspace.mutateAsync({
  name,
  sources,
  host,
  recipes: selectedRecipes,
  generateSshKey,
  profile: profileRef,
  startRecipes: selectedStartRecipes,   // ← nouveau
})
```

Ajouter la section start recipes dans le formulaire (après la section `recipes`) :

```tsx
{/* ─── Start recipes ──────────────────────────────────────────────────── */}
<div>
  <div className="flex items-center justify-between mb-2">
    <Label>{t('workspaces.form.startRecipes')}</Label>
    <Button type="button" variant="outline" size="sm" onClick={() => setShowNewStart(s => !s)}>
      {t('workspaces.form.newStartRecipe')}
    </Button>
  </div>

  {/* Picker multi-sélection */}
  {startRecipes.length > 0 && (
    <div className="flex flex-wrap gap-1 mb-2">
      {startRecipes.map((r) => {
        const selected = selectedStartRecipes.includes(r.id)
        return (
          <button
            key={r.id}
            type="button"
            onClick={() =>
              setSelectedStartRecipes(prev =>
                selected ? prev.filter(id => id !== r.id) : [...prev, r.id]
              )
            }
            className={`rounded-sm px-2 py-0.5 text-xs border transition-colors ${
              selected
                ? 'bg-primary text-primary-foreground border-primary'
                : 'bg-muted text-muted-foreground border-border hover:border-primary'
            }`}
          >
            {r.id}
          </button>
        )
      })}
    </div>
  )}

  {/* Formulaire création inline */}
  {showNewStart && (
    <div className="mt-2 rounded-md border bg-muted/30 p-3 flex flex-col gap-2">
      <div>
        <Label htmlFor="new-start-id">{t('workspaces.form.startRecipeId')}</Label>
        <Input
          id="new-start-id"
          value={newStartId}
          onChange={e => setNewStartId(e.target.value)}
          placeholder="my-start"
        />
        <p className="text-xs text-muted-foreground mt-0.5">{t('workspaces.form.startRecipeIdHint')}</p>
      </div>
      <div>
        <Label htmlFor="new-start-script">{t('workspaces.form.startRecipeScript')}</Label>
        <textarea
          id="new-start-script"
          value={newStartScript}
          onChange={e => setNewStartScript(e.target.value)}
          rows={4}
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-xs font-mono"
        />
      </div>
      <Button
        type="button"
        size="sm"
        disabled={newStartSaving || !newStartId.trim()}
        onClick={async () => {
          setNewStartSaving(true)
          try {
            await apiFetchJson('/me/start-recipes', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ id: newStartId, script: newStartScript }),
            })
            toast.success(t('workspaces.form.startRecipeCreated', { id: newStartId }))
            setSelectedStartRecipes(prev => [...prev, newStartId])
            setNewStartId('')
            setNewStartScript(t('workspaces.form.startRecipeScriptDefault'))
            setShowNewStart(false)
          } catch (err) {
            toast.error(err instanceof Error ? err.message : t('errors.generic'))
          } finally {
            setNewStartSaving(false)
          }
        }}
      >
        {t('workspaces.form.addStartRecipe')}
      </Button>
    </div>
  )}
</div>
```

- [ ] **Step 3 : Vérifier TypeScript**

```
cd frontend && npx tsc --noEmit
```
Attendu : pas d'erreur

- [ ] **Step 4 : Suite complète backend**

```
cd backend && uv run pytest -v
```
Attendu : tous PASS (y compris les nouveaux tests)

- [ ] **Step 5 : Commit final**

```bash
git add frontend/src/features/workspaces/WorkspaceCreate.tsx frontend/src/i18n/en.json frontend/src/i18n/fr.json
git commit -m "feat: WorkspaceCreate — picker start recipes + création inline, i18n"
```

---

## Récapitulatif des commits attendus

1. `feat: RecipeMeta.type + WorkspaceSpec.start_recipes/default_start`
2. `feat: RecipeRegistry valide les fichiers des recettes start`
3. `feat: filtre /recipes?type=, POST /me/start-recipes, GET /workspaces/{name}/start-recipes`
4. `feat: route WebSocket /me/workspaces/{name}/ssh avec tmux + start recipes`
5. `test: route WebSocket /workspaces/{name}/ssh — auth, validation, proxy`
6. `feat: types WorkspaceSpec.start_recipes + useStartRecipes hook`
7. `feat: WorkspaceSshTerminalWindow — terminal SSH flottant pour workspaces`
8. `feat: WorkspaceCard — renommer Open→Open VSCode, ajouter SSH session`
9. `feat: WorkspaceCreate — picker start recipes + création inline, i18n`
