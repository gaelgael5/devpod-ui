# Workspace Profile Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre la sélection d'un profil VSCode à la création d'un workspace docker-tls, dont les `customizations.vscode` sont fusionnées dans le `devcontainer.json` généré.

**Architecture:** `ProfileRef` (scope+slug) est ajouté à `WorkspaceSpec` pour la persistance et à `UpRequest` pour l'invocation. Le handler `/up` résout la référence en `Profile` via `ProfileRepository`, puis `DevPodService.up()` transmet l'objet à `_write_devcontainer` (branche `docker-tls` uniquement). Côté frontend, un `<Select>` alimenté par `useProfiles()` enrichit les deux payloads.

**Tech Stack:** FastAPI + Pydantic v2 (backend), React 18 + TanStack Query + shadcn/ui + i18next (frontend), pytest + pytest-asyncio (tests backend), Vitest + MSW + React Testing Library (tests frontend)

---

## Fichiers touchés

| Fichier | Action |
|---|---|
| `backend/src/portal/config/models.py` | Ajouter `ProfileRef`, `WorkspaceSpec.profile` |
| `backend/src/portal/devpod/service.py` | `_write_devcontainer` + `up()` — paramètre `profile` |
| `backend/src/portal/routes/workspace_ops.py` | `UpRequest.profile`, résolution ProfileRepository |
| `backend/tests/config/test_workspace_spec_profile.py` | Nouveau — tests modèles |
| `backend/tests/devpod/test_write_devcontainer.py` | Nouveau — tests injection profil |
| `backend/tests/devpod/test_service.py` | Ajouter test `up()` + profil |
| `backend/tests/routes/test_workspace_ops.py` | Ajouter tests dégradation gracieuse + rétro-compat |
| `frontend/src/features/workspaces/types.ts` | Ajouter `profile` à `WorkspaceSpec` |
| `frontend/src/features/workspaces/useWorkspaceOps.ts` | `CreateInput.profile`, enrichir les deux payloads |
| `frontend/src/features/workspaces/WorkspaceCreate.tsx` | Sélecteur profil |
| `frontend/src/features/workspaces/__tests__/WorkspaceCreate.test.tsx` | Nouveau — tests sélecteur |
| `frontend/src/i18n/fr.json` | 3 clés `workspaces.form.profile*` |
| `frontend/src/i18n/en.json` | 3 clés `workspaces.form.profile*` |
| `LESSONS.md` | Limitation SSH documentée |

---

## Task 1 : `ProfileRef` + `WorkspaceSpec.profile` (modèles backend)

**Files:**
- Modify: `backend/src/portal/config/models.py`
- Create: `backend/tests/config/test_workspace_spec_profile.py`

- [ ] **Étape 1 : Écrire les tests (rouge)**

Créer `backend/tests/config/test_workspace_spec_profile.py` :

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_workspace_spec_accepts_profile() -> None:
    from portal.config.models import WorkspaceSpec

    spec = WorkspaceSpec(
        name="myapp",
        source="github.com/org/repo",
        profile={"scope": "shared", "slug": "python-dev"},
    )
    assert spec.profile is not None
    assert spec.profile.scope == "shared"
    assert spec.profile.slug == "python-dev"


def test_workspace_spec_profile_defaults_none() -> None:
    from portal.config.models import WorkspaceSpec

    spec = WorkspaceSpec(name="myapp", source="github.com/org/repo")
    assert spec.profile is None


def test_profile_ref_rejects_invalid_scope() -> None:
    from portal.config.models import ProfileRef

    with pytest.raises(ValidationError):
        ProfileRef(scope="invalid", slug="my-profile")


def test_profile_ref_forbids_extra_fields() -> None:
    from portal.config.models import ProfileRef

    with pytest.raises(ValidationError):
        ProfileRef(scope="shared", slug="x", unknown_field="oops")


def test_workspace_spec_retro_compat_without_profile() -> None:
    """Une spec YAML sans 'profile' se charge correctement (rétro-compat)."""
    import yaml
    from portal.config.models import WorkspaceSpec

    raw = yaml.safe_load(
        "name: myapp\nsource: github.com/org/repo\nrecipes: []\n"
    )
    spec = WorkspaceSpec.model_validate(raw)
    assert spec.profile is None
```

- [ ] **Étape 2 : Vérifier que les tests échouent**

```bash
cd backend && uv run pytest tests/config/test_workspace_spec_profile.py -v
```

Résultat attendu : `ImportError` ou `ValidationError` car `ProfileRef` n'existe pas encore.

- [ ] **Étape 3 : Implémenter `ProfileRef` + `WorkspaceSpec.profile`**

Dans `backend/src/portal/config/models.py`, après l'import de `Literal` (ligne ~6) et avant `_WORKSPACE_NAME_RE` (ligne ~177) :

```python
class ProfileRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["shared", "user"]
    slug: str
```

Dans `WorkspaceSpec`, ajouter après `extra_sources` (ligne ~233) :

```python
    profile: ProfileRef | None = None
```

- [ ] **Étape 4 : Vérifier que les tests passent**

```bash
cd backend && uv run pytest tests/config/test_workspace_spec_profile.py -v
```

Résultat attendu : 5 PASSED

- [ ] **Étape 5 : Lint + mypy**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
```

Résultat attendu : aucune erreur.

- [ ] **Étape 6 : Commit**

```bash
git add backend/src/portal/config/models.py backend/tests/config/test_workspace_spec_profile.py
git commit -m "feat(models): ProfileRef + WorkspaceSpec.profile (rétro-compatible)"
```

---

## Task 2 : `_write_devcontainer` — injection du profil VSCode

**Files:**
- Modify: `backend/src/portal/devpod/service.py`
- Create: `backend/tests/devpod/test_write_devcontainer.py`

- [ ] **Étape 1 : Écrire les tests (rouge)**

Créer `backend/tests/devpod/test_write_devcontainer.py` :

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_write_devcontainer_without_profile_has_no_customizations(
    tmp_data_root: Path, global_cfg
) -> None:
    from portal.devpod.service import DevPodService

    svc = DevPodService(global_cfg=global_cfg)
    dc_path = svc._write_devcontainer("alice", "alice-myapp")
    content = json.loads(dc_path.read_text(encoding="utf-8"))
    assert "customizations" not in content


def test_write_devcontainer_with_profile_injects_extensions(
    tmp_data_root: Path, global_cfg
) -> None:
    from portal.devpod.service import DevPodService
    from portal.profiles.models import Profile

    svc = DevPodService(global_cfg=global_cfg)
    profile = Profile(
        slug="py",
        scope="user",
        name="Python Dev",
        extensions=["ms-python.python", "ms-python.debugpy"],
        settings={"editor.fontSize": 14},
    )
    dc_path = svc._write_devcontainer("alice", "alice-myapp", profile=profile)
    content = json.loads(dc_path.read_text(encoding="utf-8"))
    vscode = content["customizations"]["vscode"]
    assert "ms-python.python" in vscode["extensions"]
    assert "ms-python.debugpy" in vscode["extensions"]
    assert vscode["settings"]["editor.fontSize"] == 14


def test_write_devcontainer_profile_settings_override_existing(
    tmp_data_root: Path, global_cfg
) -> None:
    """Settings du profil sont prioritaires (fusion superficielle)."""
    from portal.devpod.service import DevPodService
    from portal.profiles.models import Profile

    svc = DevPodService(global_cfg=global_cfg)
    profile = Profile(
        slug="py",
        scope="user",
        name="Python Dev",
        extensions=[],
        settings={"editor.fontSize": 16, "python.defaultInterpreterPath": "/usr/bin/python3"},
    )
    dc_path = svc._write_devcontainer("alice", "alice-myapp", profile=profile)
    content = json.loads(dc_path.read_text(encoding="utf-8"))
    assert content["customizations"]["vscode"]["settings"]["editor.fontSize"] == 16


def test_write_devcontainer_profile_extensions_deduplicated(
    tmp_data_root: Path, global_cfg
) -> None:
    """Les doublons dans extensions sont éliminés (dict.fromkeys)."""
    from portal.devpod.service import DevPodService
    from portal.profiles.models import Profile

    svc = DevPodService(global_cfg=global_cfg)
    profile = Profile(
        slug="py",
        scope="user",
        name="Python Dev",
        extensions=["ms-python.python", "ms-python.python"],
        settings={},
    )
    dc_path = svc._write_devcontainer("alice", "alice-myapp", profile=profile)
    content = json.loads(dc_path.read_text(encoding="utf-8"))
    exts = content["customizations"]["vscode"]["extensions"]
    assert exts.count("ms-python.python") == 1


def test_write_devcontainer_empty_profile_no_customizations_block(
    tmp_data_root: Path, global_cfg
) -> None:
    """Profil sans extensions ni settings → pas de bloc customizations."""
    from portal.devpod.service import DevPodService
    from portal.profiles.models import Profile

    svc = DevPodService(global_cfg=global_cfg)
    profile = Profile(slug="empty", scope="user", name="Empty", extensions=[], settings={})
    dc_path = svc._write_devcontainer("alice", "alice-myapp", profile=profile)
    content = json.loads(dc_path.read_text(encoding="utf-8"))
    # Pas d'extensions → le bloc customizations peut être absent ou vide
    cust = content.get("customizations", {})
    exts = cust.get("vscode", {}).get("extensions", [])
    assert exts == []
```

- [ ] **Étape 2 : Vérifier que les tests échouent**

```bash
cd backend && uv run pytest tests/devpod/test_write_devcontainer.py -v
```

Résultat attendu : `TypeError` car `_write_devcontainer` n'accepte pas encore `profile`.

- [ ] **Étape 3 : Modifier `service.py` — import + signature + logique**

En tête de `backend/src/portal/devpod/service.py`, ajouter après la ligne `from ..recipes.models import RecipeMeta` :

```python
from ..profiles.models import Profile
```

Modifier la signature de `_write_devcontainer` (ligne ~332) pour ajouter le paramètre :

```python
    def _write_devcontainer(
        self,
        login: str,
        ws_id: str,
        host_port: int | None = None,
        recipes: list[RecipeMeta] | None = None,
        feature_env: dict[str, str] | None = None,
        extra_sources: list[SourceSpec] | None = None,
        profile: Profile | None = None,
    ) -> Path:
```

Ajouter le bloc d'injection juste AVANT la ligne `dc_path = tmp_dir / "devcontainer.json"` (~ligne 393), après le bloc `extra_sources` :

```python
            if profile is not None:
                frag = profile.to_customizations()["vscode"]
                if frag["extensions"] or frag["settings"]:
                    vscode = content.setdefault("customizations", {}).setdefault("vscode", {})
                    existing = vscode.get("extensions") or []
                    vscode["extensions"] = list(
                        dict.fromkeys([*existing, *frag["extensions"]])
                    )
                    vscode["settings"] = {
                        **(vscode.get("settings") or {}),
                        **frag["settings"],
                    }
```

- [ ] **Étape 4 : Vérifier que les tests passent**

```bash
cd backend && uv run pytest tests/devpod/test_write_devcontainer.py -v
```

Résultat attendu : 5 PASSED

- [ ] **Étape 5 : Lint + mypy**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
```

- [ ] **Étape 6 : Commit**

```bash
git add backend/src/portal/devpod/service.py backend/tests/devpod/test_write_devcontainer.py
git commit -m "feat(devpod): _write_devcontainer injecte customizations.vscode du profil"
```

---

## Task 3 : `DevPodService.up()` — passage du profil (docker-tls uniquement)

**Files:**
- Modify: `backend/src/portal/devpod/service.py`
- Modify: `backend/tests/devpod/test_service.py`

- [ ] **Étape 1 : Écrire le test (rouge)**

Ajouter à la fin de `backend/tests/devpod/test_service.py` :

```python
@pytest.mark.asyncio
async def test_up_docker_tls_passes_profile_to_write_devcontainer(
    tmp_data_root: Path, global_cfg, fake_devpod_bin: list[str]
) -> None:
    """up() transmet le profil à _write_devcontainer sur docker-tls."""
    import asyncio
    import json
    from unittest.mock import patch

    from portal.auth.router import provision_user
    from portal.config.models import WorkspaceSpec
    from portal.devpod.service import DevPodService
    from portal.profiles.models import Profile

    await provision_user(login="alice", sub="sub", data_root=tmp_data_root)

    profile = Profile(
        slug="py", scope="user", name="Python Dev",
        extensions=["ms-python.python"], settings={},
    )
    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    ws = WorkspaceSpec(name="myapp", source="github.com/org/repo")

    captured: list[Profile | None] = []
    original = svc._write_devcontainer

    def spy(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs.get("profile"))
        return original(*args, **kwargs)

    with patch.object(svc, "_write_devcontainer", side_effect=spy):
        ws_id = await svc.up(login="alice", ws_spec=ws, profile=profile)

    assert len(captured) == 1
    assert captured[0] is profile

    # Attendre la fin de la tâche de fond
    status_path = tmp_data_root / "routes" / f"{ws_id}.json"
    for _ in range(50):
        await asyncio.sleep(0.2)
        if status_path.exists():
            data = json.loads(status_path.read_text(encoding="utf-8"))
            if data.get("status") in ("running", "failed"):
                break
```

- [ ] **Étape 2 : Vérifier que le test échoue**

```bash
cd backend && uv run pytest tests/devpod/test_service.py::test_up_docker_tls_passes_profile_to_write_devcontainer -v
```

Résultat attendu : `TypeError` — `up()` n'accepte pas encore `profile`.

- [ ] **Étape 3 : Modifier `up()` dans `service.py`**

Modifier la signature de `up()` (ligne ~79) :

```python
    async def up(
        self,
        login: str,
        ws_spec: WorkspaceSpec,
        recipes: list[RecipeMeta] | None = None,
        feature_env: dict[str, str] | None = None,
        generate_ssh_key: bool = False,
        request_host: str = "",
        profile: Profile | None = None,
    ) -> str:
```

Modifier l'appel à `_write_devcontainer` dans la branche `docker-tls` (ligne ~136) :

```python
        if host_cfg.type == "docker-tls":
            dc_path = self._write_devcontainer(
                login, ws_id,
                host_port=host_port,
                recipes=recipes,
                feature_env=feature_env,
                extra_sources=ws_spec.extra_sources if ws_spec.extra_sources else None,
                profile=profile,
            )
```

- [ ] **Étape 4 : Vérifier que tous les tests service passent**

```bash
cd backend && uv run pytest tests/devpod/test_service.py -v
```

Résultat attendu : tous PASSED (y compris les tests existants).

- [ ] **Étape 5 : Lint + mypy**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
```

- [ ] **Étape 6 : Commit**

```bash
git add backend/src/portal/devpod/service.py backend/tests/devpod/test_service.py
git commit -m "feat(devpod): up() transmet le profil à _write_devcontainer (docker-tls)"
```

---

## Task 4 : `routes/workspace_ops.py` — `UpRequest.profile` + résolution

**Files:**
- Modify: `backend/src/portal/routes/workspace_ops.py`
- Modify: `backend/tests/routes/test_workspace_ops.py`

- [ ] **Étape 1 : Écrire les tests (rouge)**

Ajouter à `backend/tests/routes/test_workspace_ops.py` :

```python
def test_up_without_profile_field_is_retro_compatible(tmp_path: Path) -> None:
    """UpRequest sans 'profile' est accepté — rétro-compat."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/workspaces/myapp/up",
            json={"source": "git@github.com:user/repo.git"},
        )
    assert resp.status_code == 202


def test_up_with_missing_profile_degrades_gracefully(tmp_path: Path) -> None:
    """Profil inexistant → 202 (pas d'erreur), workspace démarré sans profil."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/workspaces/myapp/up",
            json={
                "source": "git@github.com:user/repo.git",
                "profile": {"scope": "user", "slug": "nonexistent-profile"},
            },
        )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "provisioning"


def test_up_with_valid_profile_ref_returns_202(tmp_path: Path) -> None:
    """Profil existant dans /data/profiles → 202 et workspace lancé."""
    import yaml

    # Créer un profil partagé sur disque
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "python-dev.yaml").write_text(
        yaml.dump(
            {"name": "Python Dev", "description": "", "extensions": ["ms-python.python"], "settings": {}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/workspaces/myapp/up",
            json={
                "source": "git@github.com:user/repo.git",
                "profile": {"scope": "shared", "slug": "python-dev"},
            },
        )
    assert resp.status_code == 202
```

- [ ] **Étape 2 : Vérifier que les tests échouent**

```bash
cd backend && uv run pytest tests/routes/test_workspace_ops.py::test_up_without_profile_field_is_retro_compatible tests/routes/test_workspace_ops.py::test_up_with_missing_profile_degrades_gracefully tests/routes/test_workspace_ops.py::test_up_with_valid_profile_ref_returns_202 -v
```

Résultat attendu : les tests avec `profile` dans le JSON échouent (`extra_fields` interdit).

- [ ] **Étape 3 : Modifier `workspace_ops.py`**

Ajouter les imports en tête du fichier (après `from ..config.models import SourceSpec, WorkspaceSpec`) :

```python
from ..config.models import ProfileRef, SourceSpec, WorkspaceSpec
from ..profiles.models import Profile
from ..profiles.repository import ProfileError, ProfileRepository
```

Ajouter `profile` à `UpRequest` :

```python
class UpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = ""
    branch: str = ""
    git_credential: str = ""
    host: str = ""
    recipes: list[str] = Field(default_factory=list)
    extra_sources: list[SourceSpec] = Field(default_factory=list)
    generate_ssh_key: bool = False
    profile: ProfileRef | None = None
```

Dans le handler `workspace_up`, ajouter la résolution du profil APRÈS la résolution des recettes (après la ligne `raise HTTPException(status_code=422, detail=f"Secret resolution failed: ...")`) et AVANT la construction de `WorkspaceSpec` :

```python
    # Résolution du profil (dégradation gracieuse si absent)
    profile_obj: Profile | None = None
    if req.profile is not None:
        try:
            repo = ProfileRepository(_data_root())
            profile_obj = await asyncio.to_thread(
                repo.get, req.profile.scope, req.profile.slug, user.login
            )
        except ProfileError:
            _log.warning(
                "workspace.profile_missing",
                scope=req.profile.scope,
                slug=req.profile.slug,
            )
```

Modifier la construction de `WorkspaceSpec` pour inclure le profil :

```python
    try:
        ws = WorkspaceSpec(
            name=name,
            source=req.source,
            branch=req.branch,
            git_credential=req.git_credential,
            host=req.host,
            recipes=req.recipes,
            extra_sources=req.extra_sources,
            profile=req.profile,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

Modifier l'appel à `svc.up()` pour passer `profile_obj` :

```python
        ws_id = await svc.up(
            login=user.login,
            ws_spec=ws,
            recipes=resolved_recipes or None,
            feature_env=feature_env or None,
            generate_ssh_key=req.generate_ssh_key,
            request_host=request_host,
            profile=profile_obj,
        )
```

- [ ] **Étape 4 : Vérifier que tous les tests routes passent**

```bash
cd backend && uv run pytest tests/routes/test_workspace_ops.py -v
```

Résultat attendu : tous PASSED (anciens + nouveaux).

- [ ] **Étape 5 : Suite complète backend**

```bash
cd backend && uv run pytest -v && uv run ruff check src/ tests/ && uv run mypy src/
```

Résultat attendu : tout vert.

- [ ] **Étape 6 : Commit**

```bash
git add backend/src/portal/routes/workspace_ops.py backend/tests/routes/test_workspace_ops.py
git commit -m "feat(routes): UpRequest.profile, résolution ProfileRepository, dégradation gracieuse"
```

---

## Task 5 : Frontend types + `useWorkspaceOps.ts`

**Files:**
- Modify: `frontend/src/features/workspaces/types.ts`
- Modify: `frontend/src/features/workspaces/useWorkspaceOps.ts`

- [ ] **Étape 1 : Ajouter `profile` à `WorkspaceSpec` dans `types.ts`**

Dans `frontend/src/features/workspaces/types.ts`, ajouter après `ssh_key?` :

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
}
```

- [ ] **Étape 2 : Modifier `useWorkspaceOps.ts`**

Ajouter `profile` à `CreateInput` :

```typescript
interface CreateInput {
  name: string
  sources: SourceEntry[]
  host: string
  recipes: string[]
  generateSshKey?: boolean
  profile?: { scope: 'shared' | 'user'; slug: string }
}
```

Modifier la `mutationFn` pour inclure `profile` dans les deux requêtes :

```typescript
    mutationFn: async ({ name, sources, host, recipes, generateSshKey, profile }: CreateInput) => {
      const primary = sources[0] ?? { url: '', branch: '', credential: '' }
      const extra = sources.slice(1).map(toSourceSpec)

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
      }
      // Add to config (ignore 409 — already exists)
      const addRes = await apiFetch('/me/workspaces', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(spec),
      })
      if (!addRes.ok && addRes.status !== 409) {
        const text = await addRes.text().catch(() => '')
        throw new Error(text || addRes.statusText)
      }
      // Start the workspace
      await apiFetchJson(`/me/workspaces/${name}/up`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source: primary.url,
          branch: primary.branch,
          git_credential: primary.credential,
          host,
          recipes,
          extra_sources: extra,
          generate_ssh_key: generateSshKey ?? false,
          profile: profile ?? null,
        }),
      })
    },
```

- [ ] **Étape 3 : Vérifier la compilation TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

Résultat attendu : aucune erreur.

- [ ] **Étape 4 : Commit**

```bash
git add frontend/src/features/workspaces/types.ts frontend/src/features/workspaces/useWorkspaceOps.ts
git commit -m "feat(workspaces): CreateInput.profile, payload enrichi dans POST /workspaces et /up"
```

---

## Task 6 : i18n — 3 clés de traduction

**Files:**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Étape 1 : Ajouter les clés dans `fr.json`**

Dans `frontend/src/i18n/fr.json`, dans le bloc `workspaces.form`, ajouter après `"removeRecipeLabel"` :

```json
      "profile": "Profil VSCode",
      "profileNone": "— aucun profil —",
      "profileShared": "(partagé)"
```

- [ ] **Étape 2 : Ajouter les clés dans `en.json`**

Ajouter les mêmes clés au même endroit dans `frontend/src/i18n/en.json` :

```json
      "profile": "VSCode Profile",
      "profileNone": "— no profile —",
      "profileShared": "(shared)"
```

- [ ] **Étape 3 : Commit**

```bash
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(i18n): clés workspaces.form.profile* (fr + en)"
```

---

## Task 7 : `WorkspaceCreate.tsx` — sélecteur de profil

**Files:**
- Modify: `frontend/src/features/workspaces/WorkspaceCreate.tsx`

- [ ] **Étape 1 : Ajouter l'import et le state**

En tête des imports de `WorkspaceCreate.tsx`, ajouter :

```tsx
import { useProfiles } from '@/features/profiles/hooks/useProfiles'
```

Dans le corps du composant `WorkspaceCreate`, après `const { data: credentials = [] }` :

```tsx
  const { data: profiles = [] } = useProfiles()
  const [profile, setProfile] = useState('')
```

Ajouter aussi la constante sentinelle en haut du fichier (après `CRED_NONE`) :

```tsx
const PROFILE_NONE = '__none__'
```

- [ ] **Étape 2 : Ajouter le `<Select>` profil dans le JSX**

Dans le JSX, après le bloc `{recipes.length > 0 && (...)}` (RecipePicker) et avant le bloc `<div className="flex items-center gap-2">` (SSH key), insérer :

```tsx
        {profiles.length > 0 && (
          <div>
            <Label className="text-xs">{t('workspaces.form.profile')}</Label>
            <Select
              value={profile || PROFILE_NONE}
              onValueChange={(v) => setProfile(v === PROFILE_NONE ? '' : v)}
            >
              <SelectTrigger className="mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={PROFILE_NONE}>
                  {t('workspaces.form.profileNone')}
                </SelectItem>
                {profiles.map((p) => (
                  <SelectItem
                    key={`${p.scope}:${p.slug}`}
                    value={`${p.scope}:${p.slug}`}
                  >
                    {p.name}
                    {p.scope === 'shared'
                      ? ` ${t('workspaces.form.profileShared')}`
                      : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
```

- [ ] **Étape 3 : Modifier `handleSubmit` pour passer `profileRef`**

Remplacer dans `handleSubmit` :

```tsx
    try {
      await createWorkspace.mutateAsync({ name, sources, host, recipes: selectedRecipes, generateSshKey })
```

Par :

```tsx
    try {
      const profileRef = profile
        ? (() => {
            const [scope, slug] = profile.split(':') as ['shared' | 'user', string]
            return { scope, slug }
          })()
        : undefined
      await createWorkspace.mutateAsync({
        name,
        sources,
        host,
        recipes: selectedRecipes,
        generateSshKey,
        profile: profileRef,
      })
```

- [ ] **Étape 4 : Vérifier la compilation TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

Résultat attendu : aucune erreur.

- [ ] **Étape 5 : Commit**

```bash
git add frontend/src/features/workspaces/WorkspaceCreate.tsx
git commit -m "feat(workspaces): sélecteur profil VSCode dans WorkspaceCreate"
```

---

## Task 8 : Tests frontend — `WorkspaceCreate`

**Files:**
- Create: `frontend/src/features/workspaces/__tests__/WorkspaceCreate.test.tsx`

- [ ] **Étape 1 : Créer le fichier de test**

```tsx
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import WorkspaceCreate from '../WorkspaceCreate'

// MSW handlers fournissent déjà GET /profiles avec 2 profils :
// - { slug: 'frontend-react', scope: 'user', name: 'Frontend React' }
// - { slug: 'python-dev', scope: 'shared', name: 'Python Dev' }

describe('WorkspaceCreate — sélecteur profil', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev'] } })
  })

  it('affiche le sélecteur profil avec option "aucun" par défaut', async () => {
    renderWithProviders(<WorkspaceCreate />)
    // Attendre que le label profil apparaisse
    expect(await screen.findByText(/profil vscode|vscode profile/i)).toBeInTheDocument()
    // L'option "aucun" est visible par défaut
    expect(screen.getByText(/aucun profil|no profile/i)).toBeInTheDocument()
  })

  it('liste les profils user et partagés avec suffixe', async () => {
    renderWithProviders(<WorkspaceCreate />)
    await screen.findByText(/profil vscode|vscode profile/i)
    // Ouvrir le Select (cliquer sur le trigger)
    const trigger = screen.getByRole('combobox')
    await userEvent.click(trigger)
    // Vérifier que Frontend React (user) est listé
    expect(await screen.findByText('Frontend React')).toBeInTheDocument()
    // Vérifier que Python Dev (shared) est listé avec suffixe
    expect(screen.getByText(/Python Dev.*partagé|Python Dev.*shared/i)).toBeInTheDocument()
  })

  it('création avec profil → les deux requêtes incluent profile', async () => {
    const capturedBodies: unknown[] = []
    const { server } = await import('@/test/server')
    const { http, HttpResponse } = await import('msw')

    server.use(
      http.post('/me/workspaces', async ({ request }) => {
        capturedBodies.push(await request.json())
        return HttpResponse.json({}, { status: 201 })
      }),
      http.post('/me/workspaces/:name/up', async ({ request }) => {
        capturedBodies.push(await request.json())
        return HttpResponse.json({ ws_id: 'alice-test', status: 'provisioning' }, { status: 202 })
      }),
    )

    renderWithProviders(<WorkspaceCreate />)
    await screen.findByText(/profil vscode|vscode profile/i)

    // Saisir le nom
    await userEvent.type(screen.getByLabelText(/^nom$/i), 'my-ws')

    // Sélectionner un profil
    const trigger = screen.getByRole('combobox')
    await userEvent.click(trigger)
    const pythonOption = await screen.findByText(/Python Dev/)
    await userEvent.click(pythonOption)

    // Soumettre
    await userEvent.click(screen.getByRole('button', { name: /créer|create/i }))

    await waitFor(() => expect(capturedBodies).toHaveLength(2))
    const [specBody, upBody] = capturedBodies as Array<{ profile?: unknown }>
    expect(specBody.profile).toEqual({ scope: 'shared', slug: 'python-dev' })
    expect(upBody.profile).toEqual({ scope: 'shared', slug: 'python-dev' })
  })

  it('création sans profil → profile null dans les deux requêtes', async () => {
    const capturedBodies: unknown[] = []
    const { server } = await import('@/test/server')
    const { http, HttpResponse } = await import('msw')

    server.use(
      http.post('/me/workspaces', async ({ request }) => {
        capturedBodies.push(await request.json())
        return HttpResponse.json({}, { status: 201 })
      }),
      http.post('/me/workspaces/:name/up', async ({ request }) => {
        capturedBodies.push(await request.json())
        return HttpResponse.json({ ws_id: 'alice-test', status: 'provisioning' }, { status: 202 })
      }),
    )

    renderWithProviders(<WorkspaceCreate />)
    await screen.findByText(/profil vscode|vscode profile/i)

    await userEvent.type(screen.getByLabelText(/^nom$/i), 'my-ws')
    // Ne pas changer le profil (reste "aucun")
    await userEvent.click(screen.getByRole('button', { name: /créer|create/i }))

    await waitFor(() => expect(capturedBodies).toHaveLength(2))
    const [specBody, upBody] = capturedBodies as Array<{ profile?: unknown }>
    expect(specBody.profile).toBeNull()
    expect(upBody.profile).toBeNull()
  })
})
```

- [ ] **Étape 2 : Lancer les tests**

```bash
cd frontend && npx vitest run src/features/workspaces/__tests__/WorkspaceCreate.test.tsx
```

Résultat attendu : 4 PASSED. Si certains échouent à cause du formulaire (nom requis, validation), ajuster les étapes de remplissage du formulaire.

- [ ] **Étape 3 : Suite complète frontend**

```bash
cd frontend && npx vitest run && npx tsc --noEmit
```

Résultat attendu : tout vert.

- [ ] **Étape 4 : Commit**

```bash
git add frontend/src/features/workspaces/__tests__/WorkspaceCreate.test.tsx
git commit -m "test(workspaces): WorkspaceCreate — sélecteur profil, payload enrichi"
```

---

## Task 9 : `LESSONS.md` — limitation SSH

**Files:**
- Modify: `LESSONS.md`

- [ ] **Étape 1 : Ajouter la leçon**

Ajouter à la fin de `LESSONS.md` :

```markdown
## [devpod/service] Profil et recettes : docker-tls uniquement
`_write_devcontainer` n'est appelé que pour les hosts `docker-tls`. Sur SSH, DevPod tourne
sur la VM distante — `--devcontainer-path` y est inexploitable (chemin local du portail).
Profil et recettes sont donc silencieusement ignorés sur SSH. Limitation préexistante, hors
périmètre du chantier 20. Ne pas contourner via `postCreateCommand` (interdit par PITFALLS).
Dégradation gracieuse : si le profil référencé est introuvable au moment du `up`, le workspace
démarre quand même sans profil (warning loggé, pas d'erreur HTTP).
```

- [ ] **Étape 2 : Commit**

```bash
git add LESSONS.md
git commit -m "docs(lessons): limitation profil/recettes docker-tls only + dégradation gracieuse"
```

---

## Task 10 : Vérification finale

- [ ] **Suite backend complète**

```bash
cd backend && uv run pytest -v && uv run ruff check src/ tests/ && uv run mypy src/
```

Résultat attendu : 0 erreur, tous tests PASSED.

- [ ] **Suite frontend complète**

```bash
cd frontend && npx vitest run && npx tsc --noEmit
```

Résultat attendu : 0 erreur TypeScript, tous tests PASSED.

- [ ] **Vérification taille de fichiers**

```bash
wc -l backend/src/portal/config/models.py backend/src/portal/devpod/service.py backend/src/portal/routes/workspace_ops.py frontend/src/features/workspaces/WorkspaceCreate.tsx
```

Résultat attendu : aucun fichier > 300 lignes.

- [ ] **Revue diff final (pas de secrets)**

```bash
git diff main..dev -- '*.py' '*.ts' '*.tsx' | grep -E '(password|secret|token|api_key)' | grep -v 'test\|example\|placeholder'
```

Résultat attendu : aucune ligne sensible.
