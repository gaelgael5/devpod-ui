# Workspace SSH Keys — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Générer une paire de clés Ed25519 par workspace à la création (opt-in), et afficher la clé publique via un bouton sur la WorkspaceCard.

**Architecture:** Nouveau module `portal/ssh_keys.py` appelé dans `DevPodService.up()` si `generate_ssh_key=True`. Un endpoint `GET /me/workspaces/{name}/ssh-key` expose la clé publique. Côté frontend, `WorkspaceCreate` ajoute un toggle, `WorkspaceCard` ajoute un bouton "Clé SSH" qui ouvre `SshKeyDialog`.

**Tech Stack:** Python `cryptography` (Ed25519, déjà dépendance), FastAPI, React 18, TanStack Query, shadcn/ui Dialog, lucide-react `Key`.

---

## Carte des fichiers

| Action | Fichier |
|--------|---------|
| Créer | `backend/src/portal/ssh_keys.py` |
| Créer | `backend/tests/ssh_keys/__init__.py` |
| Créer | `backend/tests/ssh_keys/test_ssh_keys.py` |
| Modifier | `backend/src/portal/config/models.py` (WorkspaceSpec +`ssh_key`) |
| Modifier | `backend/tests/config/test_models.py` |
| Modifier | `backend/src/portal/routes/workspace_ops.py` (UpRequest + endpoint GET) |
| Modifier | `backend/src/portal/devpod/service.py` (up + `generate_ssh_key`) |
| Modifier | `backend/tests/routes/test_workspace_ops.py` |
| Modifier | `backend/tests/devpod/test_service.py` |
| Modifier | `frontend/src/features/workspaces/types.ts` |
| Créer | `frontend/src/features/workspaces/useWorkspaceSshKey.ts` |
| Créer | `frontend/src/features/workspaces/SshKeyDialog.tsx` |
| Créer | `frontend/src/features/workspaces/SshKeyDialog.test.tsx` |
| Modifier | `frontend/src/features/workspaces/WorkspaceCard.tsx` |
| Modifier | `frontend/src/features/workspaces/WorkspaceCard.test.tsx` |
| Modifier | `frontend/src/features/workspaces/WorkspaceCreate.tsx` |
| Modifier | `frontend/src/features/workspaces/useWorkspaceOps.ts` |
| Modifier | `frontend/src/i18n/fr.json` |
| Modifier | `frontend/src/i18n/en.json` |

---

## Task 1 — Module `portal/ssh_keys.py`

**Files:**
- Créer : `backend/src/portal/ssh_keys.py`
- Créer : `backend/tests/ssh_keys/__init__.py`
- Créer : `backend/tests/ssh_keys/test_ssh_keys.py`

- [ ] **Step 1 — Écrire les tests qui échouent**

```python
# backend/tests/ssh_keys/__init__.py
# (vide)
```

```python
# backend/tests/ssh_keys/test_ssh_keys.py
from __future__ import annotations

import sys
from pathlib import Path

import pytest


def test_ensure_workspace_ssh_key_generates_valid_ed25519(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    import portal.settings as mod
    mod._settings = None

    from portal.config.store import ensure_user_dir
    ensure_user_dir("alice")

    from portal.ssh_keys import ensure_workspace_ssh_key
    pub_key = ensure_workspace_ssh_key("alice", "myapp")

    assert pub_key.startswith("ssh-ed25519 ")
    key_dir = tmp_path / "users" / "alice" / "keys" / "workspaces" / "myapp"
    assert (key_dir / "id_ed25519").exists()
    assert (key_dir / "id_ed25519.pub").exists()
    assert pub_key == (key_dir / "id_ed25519.pub").read_text(encoding="utf-8").strip()


def test_ensure_workspace_ssh_key_private_key_has_600_perms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if sys.platform == "win32":
        pytest.skip("POSIX permissions not applicable on Windows")

    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    import portal.settings as mod
    mod._settings = None

    from portal.config.store import ensure_user_dir
    ensure_user_dir("alice")

    from portal.ssh_keys import ensure_workspace_ssh_key
    ensure_workspace_ssh_key("alice", "myapp")

    import stat
    priv_path = tmp_path / "users" / "alice" / "keys" / "workspaces" / "myapp" / "id_ed25519"
    assert stat.S_IMODE(priv_path.stat().st_mode) == 0o600


def test_ensure_workspace_ssh_key_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    import portal.settings as mod
    mod._settings = None

    from portal.config.store import ensure_user_dir
    ensure_user_dir("alice")

    from portal.ssh_keys import ensure_workspace_ssh_key
    pub1 = ensure_workspace_ssh_key("alice", "myapp")
    pub2 = ensure_workspace_ssh_key("alice", "myapp")

    assert pub1 == pub2


def test_ensure_workspace_ssh_key_different_workspaces_get_different_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    import portal.settings as mod
    mod._settings = None

    from portal.config.store import ensure_user_dir
    ensure_user_dir("alice")

    from portal.ssh_keys import ensure_workspace_ssh_key
    pub_a = ensure_workspace_ssh_key("alice", "myapp")
    pub_b = ensure_workspace_ssh_key("alice", "otherapp")

    assert pub_a != pub_b
```

- [ ] **Step 2 — Vérifier que les tests échouent**

```
cd backend && uv run pytest tests/ssh_keys/ -v
```

Résultat attendu : `ImportError: cannot import name 'ensure_workspace_ssh_key' from 'portal.ssh_keys'`

- [ ] **Step 3 — Implémenter `portal/ssh_keys.py`**

```python
# backend/src/portal/ssh_keys.py
from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from .config.store import safe_user_path


def ensure_workspace_ssh_key(login: str, workspace_name: str) -> str:
    """Génère la paire Ed25519 pour un workspace si absente. Retourne la clé publique."""
    key_dir = safe_user_path(login, "keys", "workspaces", workspace_name)
    pub_path = key_dir / "id_ed25519.pub"
    priv_path = key_dir / "id_ed25519"

    if pub_path.exists():
        return pub_path.read_text(encoding="utf-8").strip()

    key_dir.mkdir(parents=True, exist_ok=True)

    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption())
    public_bytes = private_key.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)
    public_str = public_bytes.decode("ascii") + f" devpod:{login}/{workspace_name}"

    _atomic_write(priv_path, private_pem, mode=0o600)
    _atomic_write(pub_path, public_str.encode("ascii"), mode=0o644)

    return public_str


def _atomic_write(path: Path, data: bytes, mode: int) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        with contextlib.suppress(OSError):
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
```

- [ ] **Step 4 — Vérifier que les tests passent**

```
cd backend && uv run pytest tests/ssh_keys/ -v
```

Résultat attendu : 4 tests PASSED

- [ ] **Step 5 — Lint + mypy**

```
cd backend && uv run ruff check src/portal/ssh_keys.py && uv run mypy src/portal/ssh_keys.py
```

Résultat attendu : no errors

- [ ] **Step 6 — Commit**

```
git add backend/src/portal/ssh_keys.py backend/tests/ssh_keys/
git commit -m "feat(workspace): module ssh_keys — génération paire Ed25519 par workspace"
```

---

## Task 2 — `WorkspaceSpec.ssh_key` dans `config/models.py`

**Files:**
- Modifier : `backend/src/portal/config/models.py` (ligne ~190, classe `WorkspaceSpec`)
- Modifier : `backend/tests/config/test_models.py`

- [ ] **Step 1 — Écrire le test qui échoue**

Ajouter à la fin de `backend/tests/config/test_models.py` :

```python
def test_workspace_spec_ssh_key_defaults_to_false() -> None:
    from portal.config.models import WorkspaceSpec
    ws = WorkspaceSpec(name="myapp", source="git@github.com:org/repo.git")
    assert ws.ssh_key is False


def test_workspace_spec_ssh_key_can_be_set() -> None:
    from portal.config.models import WorkspaceSpec
    ws = WorkspaceSpec(name="myapp", source="git@github.com:org/repo.git", ssh_key=True)
    assert ws.ssh_key is True
```

- [ ] **Step 2 — Vérifier que les tests échouent**

```
cd backend && uv run pytest tests/config/test_models.py -k "ssh_key" -v
```

Résultat attendu : `ValidationError` ou `AttributeError`

- [ ] **Step 3 — Ajouter le champ dans `WorkspaceSpec`**

Dans `backend/src/portal/config/models.py`, chercher la classe `WorkspaceSpec`. Ajouter le champ après `extra_sources` :

```python
class WorkspaceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source: str
    branch: str = ""
    git_credential: str = ""
    host: str = ""
    template: str = ""
    devcontainer_path: str = ""
    recipes: list[str] = Field(default_factory=list)
    ide: str = ""
    idle_timeout: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    expose: WorkspaceExpose = Field(default_factory=WorkspaceExpose)
    extra_sources: list[SourceSpec] = Field(default_factory=list)
    ssh_key: bool = False          # ← ajout
    # ... validators existants inchangés
```

- [ ] **Step 4 — Vérifier que les tests passent**

```
cd backend && uv run pytest tests/config/test_models.py -v
```

Résultat attendu : tous PASSED

- [ ] **Step 5 — Commit**

```
git add backend/src/portal/config/models.py backend/tests/config/test_models.py
git commit -m "feat(workspace): WorkspaceSpec.ssh_key — flag persistance clé SSH"
```

---

## Task 3 — Endpoint `GET /me/workspaces/{name}/ssh-key`

**Files:**
- Modifier : `backend/src/portal/routes/workspace_ops.py`
- Modifier : `backend/tests/routes/test_workspace_ops.py`

- [ ] **Step 1 — Écrire les tests qui échouent**

Ajouter à la fin de `backend/tests/routes/test_workspace_ops.py` :

```python
def test_get_ssh_key_returns_404_when_not_generated(tmp_path: Path) -> None:
    """GET /me/workspaces/{name}/ssh-key retourne 404 si la clé n'existe pas."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/me/workspaces/myapp/ssh-key")
    assert resp.status_code == 404


def test_get_ssh_key_returns_404_for_invalid_name(tmp_path: Path) -> None:
    """GET /me/workspaces/{name}/ssh-key rejette les noms invalides."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/me/workspaces/INVALID_NAME/ssh-key")
    assert resp.status_code == 422


def test_get_ssh_key_returns_200_when_key_exists(tmp_path: Path) -> None:
    """GET /me/workspaces/{name}/ssh-key retourne 200 + public_key si la clé existe."""
    # _make_app provisionne alice (crée le répertoire user) et positionne PORTAL_DATA_ROOT
    app = _make_app(tmp_path)

    # Générer la clé directement via le module (simule DevPodService.up avec generate_ssh_key=True)
    from portal.ssh_keys import ensure_workspace_ssh_key
    expected_pub = ensure_workspace_ssh_key("alice", "myapp")

    with TestClient(app) as client:
        resp = client.get("/me/workspaces/myapp/ssh-key")

    assert resp.status_code == 200
    data = resp.json()
    assert "public_key" in data
    assert data["public_key"].startswith("ssh-ed25519 ")
    assert data["public_key"] == expected_pub
```

- [ ] **Step 2 — Vérifier que les tests échouent**

```
cd backend && uv run pytest tests/routes/test_workspace_ops.py -k "ssh_key" -v
```

Résultat attendu : `404 Not Found` (route inexistante)

- [ ] **Step 3 — Ajouter l'endpoint dans `workspace_ops.py`**

Ajouter après la route `workspace_status` (fin du fichier) dans `backend/src/portal/routes/workspace_ops.py` :

```python
@router.get("/workspaces/{name}/ssh-key")
async def get_workspace_ssh_key(
    name: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, str]:
    _validate_name(name)
    pub_path = safe_user_path(user.login, "keys", "workspaces", name) / "id_ed25519.pub"
    if not pub_path.exists():
        raise HTTPException(
            status_code=404,
            detail="SSH key not generated for this workspace",
        )
    return {"public_key": pub_path.read_text(encoding="utf-8").strip()}
```

- [ ] **Step 4 — Vérifier que les tests passent**

```
cd backend && uv run pytest tests/routes/test_workspace_ops.py -k "ssh_key" -v
```

Résultat attendu : 3 tests PASSED

- [ ] **Step 5 — Lint + mypy**

```
cd backend && uv run ruff check src/portal/routes/workspace_ops.py && uv run mypy src/portal/routes/workspace_ops.py
```

- [ ] **Step 6 — Commit**

```
git add backend/src/portal/routes/workspace_ops.py backend/tests/routes/test_workspace_ops.py
git commit -m "feat(workspace): GET /me/workspaces/{name}/ssh-key — exposition clé publique"
```

---

## Task 4 — `generate_ssh_key` dans `UpRequest` + `DevPodService.up()`

**Files:**
- Modifier : `backend/src/portal/routes/workspace_ops.py` (`UpRequest` + appel `svc.up`)
- Modifier : `backend/src/portal/devpod/service.py` (paramètre `generate_ssh_key`)
- Modifier : `backend/tests/routes/test_workspace_ops.py`
- Modifier : `backend/tests/devpod/test_service.py`

- [ ] **Step 1 — Écrire les tests qui échouent**

Ajouter dans `backend/tests/routes/test_workspace_ops.py` :

```python
def test_up_with_generate_ssh_key_creates_key_file(tmp_path: Path) -> None:
    """POST up avec generate_ssh_key=True génère la paire de clés sur disque."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/workspaces/myapp/up",
            json={"source": "git@github.com:user/repo.git", "generate_ssh_key": True},
        )
    assert resp.status_code == 202

    pub_path = tmp_path / "users" / "alice" / "keys" / "workspaces" / "myapp" / "id_ed25519.pub"
    assert pub_path.exists(), "La clé publique doit exister après up avec generate_ssh_key=True"
    assert pub_path.read_text(encoding="utf-8").strip().startswith("ssh-ed25519 ")


def test_up_without_generate_ssh_key_does_not_create_key(tmp_path: Path) -> None:
    """POST up sans generate_ssh_key ne crée pas de clé."""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/workspaces/myapp/up",
            json={"source": "git@github.com:user/repo.git"},
        )
    assert resp.status_code == 202

    pub_path = tmp_path / "users" / "alice" / "keys" / "workspaces" / "myapp" / "id_ed25519.pub"
    assert not pub_path.exists(), "Aucune clé ne doit être créée sans generate_ssh_key"
```

Ajouter dans `backend/tests/devpod/test_service.py` :

```python
@pytest.mark.asyncio
async def test_up_with_generate_ssh_key_creates_key(
    tmp_data_root: Path, global_cfg, fake_devpod_bin: list[str]
) -> None:
    """up(generate_ssh_key=True) crée la paire de clés avant de lancer devpod."""
    from portal.auth.router import provision_user
    from portal.config.models import WorkspaceSpec
    from portal.devpod.service import DevPodService

    await provision_user(login="alice", sub="sub", data_root=tmp_data_root)

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    ws = WorkspaceSpec(name="myapp", source="git@github.com:user/repo.git")

    await svc.up(login="alice", ws_spec=ws, generate_ssh_key=True)

    pub_path = (
        tmp_data_root / "users" / "alice" / "keys" / "workspaces" / "myapp" / "id_ed25519.pub"
    )
    assert pub_path.exists()
    assert pub_path.read_text(encoding="utf-8").strip().startswith("ssh-ed25519 ")
```

- [ ] **Step 2 — Vérifier que les tests échouent**

```
cd backend && uv run pytest tests/routes/test_workspace_ops.py -k "generate_ssh_key" -v
cd backend && uv run pytest tests/devpod/test_service.py -k "generate_ssh_key" -v
```

Résultat attendu : tests échouent (champ `generate_ssh_key` ignoré / `up()` sans paramètre)

- [ ] **Step 3 — Ajouter `generate_ssh_key` dans `UpRequest`**

Dans `backend/src/portal/routes/workspace_ops.py`, modifier `UpRequest` :

```python
class UpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = ""
    branch: str = ""
    git_credential: str = ""
    host: str = ""
    recipes: list[str] = Field(default_factory=list)
    extra_sources: list[SourceSpec] = Field(default_factory=list)
    generate_ssh_key: bool = False   # ← ajout
```

Modifier l'appel à `svc.up()` dans la route `workspace_up` (chercher `ws_id = await svc.up(`) :

```python
    ws_id = await svc.up(
        login=user.login,
        ws_spec=ws,
        recipes=resolved_recipes or None,
        feature_env=feature_env or None,
        generate_ssh_key=req.generate_ssh_key,
    )
```

- [ ] **Step 4 — Ajouter `generate_ssh_key` dans `DevPodService.up()`**

Dans `backend/src/portal/devpod/service.py`, modifier la signature de `up()` :

```python
    async def up(
        self,
        login: str,
        ws_spec: WorkspaceSpec,
        recipes: list[RecipeMeta] | None = None,
        feature_env: dict[str, str] | None = None,
        generate_ssh_key: bool = False,
    ) -> str:
```

Ajouter la génération juste après `ws_id = self._ws_id(...)`, avant `base_env = build_env(...)` :

```python
        ws_id = self._ws_id(login, ws_spec.name)

        if generate_ssh_key:
            from ..ssh_keys import ensure_workspace_ssh_key
            await asyncio.to_thread(ensure_workspace_ssh_key, login, ws_spec.name)

        # Env de base (DEVPOD_HOME, DOCKER_*) — sans les secrets utilisateur
        base_env = build_env(login=login, ws_spec=ws_spec, global_cfg=self._global_cfg)
```

- [ ] **Step 5 — Vérifier que les tests passent**

```
cd backend && uv run pytest tests/routes/test_workspace_ops.py tests/devpod/test_service.py -v
```

Résultat attendu : tous PASSED

- [ ] **Step 6 — Suite complète**

```
cd backend && uv run pytest -v
```

Résultat attendu : toute la suite passe

- [ ] **Step 7 — Lint + mypy**

```
cd backend && uv run ruff check src/ && uv run mypy src/
```

- [ ] **Step 8 — Commit**

```
git add backend/src/portal/routes/workspace_ops.py backend/src/portal/devpod/service.py backend/tests/routes/test_workspace_ops.py backend/tests/devpod/test_service.py
git commit -m "feat(workspace): generate_ssh_key dans UpRequest + DevPodService.up()"
```

---

## Task 5 — Frontend : types + hook + i18n

**Files:**
- Modifier : `frontend/src/features/workspaces/types.ts`
- Créer : `frontend/src/features/workspaces/useWorkspaceSshKey.ts`
- Modifier : `frontend/src/i18n/fr.json`
- Modifier : `frontend/src/i18n/en.json`

- [ ] **Step 1 — Ajouter `ssh_key` dans `types.ts`**

Dans `frontend/src/features/workspaces/types.ts`, ajouter `ssh_key` à `WorkspaceSpec` :

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
}
```

- [ ] **Step 2 — Créer `useWorkspaceSshKey.ts`**

```typescript
// frontend/src/features/workspaces/useWorkspaceSshKey.ts
import { useQuery } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'

export interface SshKeyResponse {
  public_key: string
}

export function useWorkspaceSshKey(name: string, enabled: boolean) {
  return useQuery<SshKeyResponse>({
    queryKey: ['workspace-ssh-key', name],
    queryFn: () => apiFetchJson<SshKeyResponse>(`/me/workspaces/${name}/ssh-key`),
    enabled,
    retry: false,
  })
}
```

- [ ] **Step 3 — Ajouter les clés i18n**

Dans `frontend/src/i18n/fr.json`, ajouter dans `"workspaces"` (après `"confirm"`) :

```json
"sshKey": {
  "button": "Clé SSH",
  "title": "Clé publique SSH",
  "hint": "Copiez cette clé dans GitHub → Settings → Deploy keys ou GitLab → Dépôt → Paramètres → Clés de déploiement.",
  "copy": "Copier",
  "copied": "Copié !",
  "notGenerated": "Clé SSH non disponible pour ce workspace."
}
```

Dans `"workspaces.form"`, ajouter :

```json
"generateSshKey": "Générer une clé SSH pour ce workspace"
```

Dans `frontend/src/i18n/en.json`, mêmes clés en anglais :

```json
"sshKey": {
  "button": "SSH Key",
  "title": "SSH Public Key",
  "hint": "Paste this key into GitHub → Settings → Deploy keys or GitLab → Repository → Settings → Deploy Keys.",
  "copy": "Copy",
  "copied": "Copied!",
  "notGenerated": "SSH key not available for this workspace."
}
```

Dans `"workspaces.form"` :

```json
"generateSshKey": "Generate an SSH key for this workspace"
```

- [ ] **Step 4 — Vérifier TypeScript**

```
cd frontend && npx tsc --noEmit
```

Résultat attendu : no errors

- [ ] **Step 5 — Commit**

```
git add frontend/src/features/workspaces/types.ts frontend/src/features/workspaces/useWorkspaceSshKey.ts frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(workspace): types ssh_key + hook useWorkspaceSshKey + traductions"
```

---

## Task 6 — `SshKeyDialog.tsx`

**Files:**
- Créer : `frontend/src/features/workspaces/SshKeyDialog.tsx`
- Créer : `frontend/src/features/workspaces/SshKeyDialog.test.tsx`

- [ ] **Step 1 — Écrire le test qui échoue**

```typescript
// frontend/src/features/workspaces/SshKeyDialog.test.tsx
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import SshKeyDialog from './SshKeyDialog'

vi.mock('./useWorkspaceSshKey', () => ({
  useWorkspaceSshKey: (_name: string, enabled: boolean) => ({
    data: enabled ? { public_key: 'ssh-ed25519 AAAAB3NzaC1lZDI1NTE5 devpod:alice/myapp' } : undefined,
    isLoading: false,
    isError: false,
  }),
}))

describe('SshKeyDialog', () => {
  it('affiche la clé publique quand open=true', () => {
    renderWithProviders(
      <SshKeyDialog workspaceName="myapp" open={true} onOpenChange={vi.fn()} />
    )
    expect(screen.getByDisplayValue(/ssh-ed25519/)).toBeInTheDocument()
  })

  it('affiche le bouton Copier', () => {
    renderWithProviders(
      <SshKeyDialog workspaceName="myapp" open={true} onOpenChange={vi.fn()} />
    )
    expect(screen.getByRole('button', { name: /copier|copy/i })).toBeInTheDocument()
  })

  it("n'affiche pas la clé quand open=false", () => {
    renderWithProviders(
      <SshKeyDialog workspaceName="myapp" open={false} onOpenChange={vi.fn()} />
    )
    expect(screen.queryByDisplayValue(/ssh-ed25519/)).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2 — Vérifier que les tests échouent**

```
cd frontend && npx vitest run src/features/workspaces/SshKeyDialog.test.tsx
```

Résultat attendu : `Cannot find module './SshKeyDialog'`

- [ ] **Step 3 — Implémenter `SshKeyDialog.tsx`**

```tsx
// frontend/src/features/workspaces/SshKeyDialog.tsx
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Copy } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useWorkspaceSshKey } from './useWorkspaceSshKey'

interface Props {
  workspaceName: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export default function SshKeyDialog({ workspaceName, open, onOpenChange }: Props) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  const { data, isLoading, isError } = useWorkspaceSshKey(workspaceName, open)

  async function handleCopy() {
    if (!data) return
    await navigator.clipboard.writeText(data.public_key)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('workspaces.sshKey.title')}</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">{t('workspaces.sshKey.hint')}</p>
        {isLoading && <p className="text-sm text-muted-foreground">…</p>}
        {isError && (
          <p className="text-sm text-destructive">{t('workspaces.sshKey.notGenerated')}</p>
        )}
        {data && (
          <div className="flex flex-col gap-2">
            <textarea
              readOnly
              value={data.public_key}
              rows={4}
              className="w-full rounded-md border bg-muted px-3 py-2 font-mono text-xs resize-none"
            />
            <Button size="sm" variant="outline" className="self-start" onClick={handleCopy}>
              {copied
                ? <><Check className="h-4 w-4 mr-1" />{t('workspaces.sshKey.copied')}</>
                : <><Copy className="h-4 w-4 mr-1" />{t('workspaces.sshKey.copy')}</>
              }
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 4 — Vérifier que les tests passent**

```
cd frontend && npx vitest run src/features/workspaces/SshKeyDialog.test.tsx
```

Résultat attendu : 3 tests PASSED

- [ ] **Step 5 — Commit**

```
git add frontend/src/features/workspaces/SshKeyDialog.tsx frontend/src/features/workspaces/SshKeyDialog.test.tsx
git commit -m "feat(workspace): SshKeyDialog — affichage clé publique + bouton copier"
```

---

## Task 7 — `WorkspaceCard.tsx` : bouton Clé SSH

**Files:**
- Modifier : `frontend/src/features/workspaces/WorkspaceCard.tsx`
- Modifier : `frontend/src/features/workspaces/WorkspaceCard.test.tsx`

- [ ] **Step 1 — Écrire les tests qui échouent**

Ajouter dans `backend/tests/...` — non, dans `frontend/src/features/workspaces/WorkspaceCard.test.tsx`, ajouter à la fin du `describe` existant :

```typescript
  it('affiche le bouton Clé SSH quand spec.ssh_key=true', () => {
    const spec: WorkspaceSpec = { ...SPEC, ssh_key: true }
    renderWithProviders(
      <WorkspaceCard
        spec={spec}
        status={{ ws_id: 'alice-myapp', status: 'running', url: 'https://x' }}
        onStop={vi.fn()}
        onDelete={vi.fn()}
      />
    )
    expect(screen.getByRole('button', { name: /clé ssh|ssh key/i })).toBeInTheDocument()
  })

  it("n'affiche pas le bouton Clé SSH quand spec.ssh_key=false", () => {
    const spec: WorkspaceSpec = { ...SPEC, ssh_key: false }
    renderWithProviders(
      <WorkspaceCard
        spec={spec}
        status={{ ws_id: 'alice-myapp', status: 'running', url: 'https://x' }}
        onStop={vi.fn()}
        onDelete={vi.fn()}
      />
    )
    expect(screen.queryByRole('button', { name: /clé ssh|ssh key/i })).not.toBeInTheDocument()
  })
```

- [ ] **Step 2 — Vérifier que les tests échouent**

```
cd frontend && npx vitest run src/features/workspaces/WorkspaceCard.test.tsx
```

Résultat attendu : 2 nouveaux tests FAILED

- [ ] **Step 3 — Modifier `WorkspaceCard.tsx`**

Remplacer le contenu complet du fichier :

```tsx
// frontend/src/features/workspaces/WorkspaceCard.tsx
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Key } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { WorkspaceSpec, WorkspaceStatus, WorkspaceStatusValue } from './types'
import SshKeyDialog from './SshKeyDialog'

const STATUS_CLASS: Record<WorkspaceStatusValue, string> = {
  running: 'bg-green-500/10 text-green-600 border-green-500/30',
  stopped: 'bg-yellow-500/10 text-yellow-600 border-yellow-500/30',
  provisioning: 'bg-primary/10 text-primary border-primary/30',
  failed: 'bg-destructive/10 text-destructive border-destructive/30',
  unknown: 'bg-muted text-muted-foreground border-border',
}

interface Props {
  spec: WorkspaceSpec
  status: WorkspaceStatus
  onStop: (name: string) => void
  onDelete: (name: string) => void
  onStart?: (name: string) => void
}

export default function WorkspaceCard({ spec, status, onStop, onDelete, onStart }: Props) {
  const { t } = useTranslation()
  const [sshKeyOpen, setSshKeyOpen] = useState(false)
  const s = status.status

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <div className="font-semibold text-foreground">{spec.name}</div>
          <div className="text-xs text-muted-foreground">{spec.source}</div>
        </div>
        <Badge
          variant="outline"
          className={cn('shrink-0 text-xs', STATUS_CLASS[s])}
        >
          {s === 'provisioning' && '⟳ '}{t(`workspaces.status.${s}`)}
        </Badge>
      </div>

      {spec.recipes.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1">
          {spec.recipes.map((r) => (
            <span
              key={r}
              className="rounded-sm bg-primary/10 px-2 py-0.5 text-xs text-primary"
            >
              {r}
            </span>
          ))}
        </div>
      )}

      {s === 'provisioning' && (
        <div className="mb-3 h-1 overflow-hidden rounded-full bg-muted">
          <div className="h-full w-1/2 animate-pulse rounded-full bg-primary" />
        </div>
      )}

      <div className="flex gap-2">
        {s === 'running' && status.url && (
          <Button size="sm" asChild>
            <a href={status.url} target="_blank" rel="noopener noreferrer">
              {t('workspaces.actions.open')}
            </a>
          </Button>
        )}
        {s === 'running' && (
          <Button size="sm" variant="outline" onClick={() => onStop(spec.name)}>
            {t('workspaces.actions.stop')}
          </Button>
        )}
        {s === 'stopped' && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => onStart?.(spec.name)}
            disabled={!onStart}
          >
            {t('workspaces.actions.start')}
          </Button>
        )}
        {(s === 'stopped' || s === 'unknown' || s === 'failed') && (
          <Button
            size="sm"
            variant="ghost"
            className="text-destructive hover:text-destructive"
            onClick={() => onDelete(spec.name)}
          >
            {t('workspaces.actions.delete')}
          </Button>
        )}
        {s === 'failed' && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => onStart?.(spec.name)}
            disabled={!onStart}
          >
            {t('workspaces.actions.retry')}
          </Button>
        )}
        {spec.ssh_key && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setSshKeyOpen(true)}
            aria-label={t('workspaces.sshKey.button')}
          >
            <Key className="h-4 w-4" />
          </Button>
        )}
      </div>

      {spec.ssh_key && (
        <SshKeyDialog
          workspaceName={spec.name}
          open={sshKeyOpen}
          onOpenChange={setSshKeyOpen}
        />
      )}
    </div>
  )
}
```

- [ ] **Step 4 — Vérifier que tous les tests passent**

```
cd frontend && npx vitest run src/features/workspaces/WorkspaceCard.test.tsx
```

Résultat attendu : tous PASSED (anciens + nouveaux)

- [ ] **Step 5 — Commit**

```
git add frontend/src/features/workspaces/WorkspaceCard.tsx frontend/src/features/workspaces/WorkspaceCard.test.tsx
git commit -m "feat(workspace): WorkspaceCard — bouton Clé SSH + SshKeyDialog"
```

---

## Task 8 — `WorkspaceCreate.tsx` + `useWorkspaceOps.ts` : toggle generate_ssh_key

**Files:**
- Modifier : `frontend/src/features/workspaces/WorkspaceCreate.tsx`
- Modifier : `frontend/src/features/workspaces/useWorkspaceOps.ts`
- Modifier : `frontend/src/features/workspaces/WorkspaceCreate.test.tsx`

- [ ] **Step 1 — Écrire le test qui échoue**

Ouvrir `frontend/src/features/workspaces/WorkspaceCreate.test.tsx` et ajouter un test :

```typescript
it('affiche le toggle Générer une clé SSH', () => {
  renderWithProviders(<WorkspaceCreate />)
  expect(
    screen.getByRole('checkbox', { name: /générer.*clé ssh|generate.*ssh key/i })
  ).toBeInTheDocument()
})
```

- [ ] **Step 2 — Vérifier que le test échoue**

```
cd frontend && npx vitest run src/features/workspaces/WorkspaceCreate.test.tsx
```

Résultat attendu : test FAILED (checkbox introuvable)

- [ ] **Step 3 — Modifier `useWorkspaceOps.ts`**

Ajouter `generateSshKey` à `CreateInput` et l'utiliser dans la mutation :

```typescript
interface CreateInput {
  name: string
  sources: SourceEntry[]
  host: string
  recipes: string[]
  generateSshKey?: boolean
}
```

Dans `mutationFn`, modifier le `spec` et le corps du `up` :

```typescript
    mutationFn: async ({ name, sources, host, recipes, generateSshKey }: CreateInput) => {
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
        }),
      })
    },
```

- [ ] **Step 4 — Modifier `WorkspaceCreate.tsx`**

Ajouter l'import `Label` est déjà présent. Ajouter l'état et le champ dans le formulaire.

Ajouter `const [generateSshKey, setGenerateSshKey] = useState(false)` après les autres `useState` :

```typescript
  const [generateSshKey, setGenerateSshKey] = useState(false)
```

Modifier l'appel dans `handleSubmit` :

```typescript
      await createWorkspace.mutateAsync({ name, sources, host, recipes: selectedRecipes, generateSshKey })
```

Ajouter le champ dans le formulaire JSX, juste avant `{serverError && ...}` :

```tsx
        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            id="ws-ssh-key"
            checked={generateSshKey}
            onChange={e => setGenerateSshKey(e.target.checked)}
            className="h-4 w-4 rounded border-input"
          />
          <Label htmlFor="ws-ssh-key" className="cursor-pointer font-normal">
            {t('workspaces.form.generateSshKey')}
          </Label>
        </div>
```

- [ ] **Step 5 — Vérifier que tous les tests passent**

```
cd frontend && npx vitest run src/features/workspaces/WorkspaceCreate.test.tsx
```

Résultat attendu : tous PASSED

- [ ] **Step 6 — Suite complète frontend**

```
cd frontend && npx vitest run
```

Résultat attendu : toute la suite passe

- [ ] **Step 7 — TypeScript**

```
cd frontend && npx tsc --noEmit
```

- [ ] **Step 8 — Commit**

```
git add frontend/src/features/workspaces/WorkspaceCreate.tsx frontend/src/features/workspaces/useWorkspaceOps.ts frontend/src/features/workspaces/WorkspaceCreate.test.tsx
git commit -m "feat(workspace): toggle generate_ssh_key dans WorkspaceCreate"
```

---

## Vérification finale

- [ ] **Suite backend complète**

```
cd backend && uv run pytest -v
```

- [ ] **Suite frontend complète**

```
cd frontend && npx vitest run
```

- [ ] **Lint + mypy backend**

```
cd backend && uv run ruff check src/ && uv run ruff format --check src/ && uv run mypy src/
```

- [ ] **TypeScript frontend**

```
cd frontend && npx tsc --noEmit
```
