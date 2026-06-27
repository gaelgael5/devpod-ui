# Shelve on Delete — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Avant de supprimer un workspace, pousser le travail en cours (WIP + commits non poussés) sur une branche `recovery-JJ-MM-AA-HH-MM`; si le push échoue → 409 sans suppression.

**Architecture:** Script bash exécuté dans le conteneur via `devpod ssh <ws_id> --command` ; parsing de la sortie stdout (NOTHING_TO_SHELVE ou SHELVED:<branch>) ; HTTPException(409) si rc ≠ 0. Frontend : dialog de confirmation + toast recovery_branch.

**Tech Stack:** Python 3.12 asyncio, FastAPI, structlog, base64 ; React 18, TanStack Query, sonner toast, shadcn Dialog, i18next.

---

## Structure des fichiers

| Fichier | Action |
|---------|--------|
| `backend/src/portal/devpod/shelve.py` | Créer — SHELVE_SCRIPT + `shelve_if_pending()` |
| `backend/src/portal/devpod/service.py` | Modifier — `delete()` appelle shelve, retourne dict |
| `backend/src/portal/routes/workspace_ops.py` | Modifier — retourne `recovery_branch` |
| `backend/tests/devpod/test_shelve.py` | Créer — tests unitaires shelve |
| `backend/tests/routes/test_workspace_ops.py` | Modifier — tests delete avec shelve |
| `frontend/src/features/workspaces/useWorkspaceOps.ts` | Modifier — recovery toast, 409 |
| `frontend/src/features/workspaces/WorkspaceCard.tsx` | Modifier — dialog de confirmation |
| `frontend/src/i18n/en.json` | Modifier — nouvelles clés |
| `frontend/src/i18n/fr.json` | Modifier — nouvelles clés |

---

## Task 1 : Backend — shelve.py + intégration service.py + workspace_ops.py

**Files:**
- Create: `backend/src/portal/devpod/shelve.py`
- Modify: `backend/src/portal/devpod/service.py` (méthode `delete`)
- Modify: `backend/src/portal/routes/workspace_ops.py` (endpoint delete)

### Étape 1.1 — Écrire le test rouge pour `shelve_if_pending` (NOTHING_TO_SHELVE)

Créer `backend/tests/devpod/test_shelve.py` (créer aussi `backend/tests/devpod/__init__.py` si absent) :

```python
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from portal.devpod.shelve import shelve_if_pending


def _make_proc(stdout: bytes, rc: int) -> MagicMock:
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    proc.returncode = rc
    return proc


@pytest.mark.asyncio
async def test_shelve_nothing_to_shelve():
    proc = _make_proc(b"NOTHING_TO_SHELVE\n", 0)
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await shelve_if_pending(["devpod"], "alice-myws", {"PATH": "/usr/bin"})
    assert result is None
```

- [ ] Créer `backend/tests/devpod/__init__.py` (vide)
- [ ] Créer `backend/tests/devpod/test_shelve.py` avec le test ci-dessus

```bash
cd backend && uv run pytest tests/devpod/test_shelve.py::test_shelve_nothing_to_shelve -v
```

Attendu : FAIL (ImportError — `portal.devpod.shelve` n'existe pas)

### Étape 1.2 — Créer `backend/src/portal/devpod/shelve.py`

```python
from __future__ import annotations

import asyncio
import base64

import structlog
from fastapi import HTTPException

_log = structlog.get_logger(__name__)

SHELVE_SCRIPT = r"""#!/usr/bin/env bash
set -eu

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "NOTHING_TO_SHELVE"; exit 0
fi

dirty=0
[ -n "$(git status --porcelain)" ] && dirty=1

upstream="$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || true)"
ahead=0
[ -n "$upstream" ] && ahead="$(git rev-list --count @{u}..HEAD 2>/dev/null || echo 0)"

if [ "$dirty" -eq 0 ] && [ "$ahead" -eq 0 ]; then
  echo "NOTHING_TO_SHELVE"; exit 0
fi

br="recovery-$(date +%d-%m-%y-%H-%M)"
i=1; base="$br"
while git ls-remote --exit-code --heads origin "$br" >/dev/null 2>&1; do
  i=$((i+1)); br="$base-$i"
done

git checkout -b "$br"
git add -A
git commit -m "WIP shelve $br" || true
git push -u origin "$br"
echo "SHELVED:$br"
"""


async def shelve_if_pending(
    devpod_bin: list[str],
    ws_id: str,
    env: dict[str, str],
) -> str | None:
    """Lance le script de shelve via devpod ssh.

    Retourne la branche créée, None si rien à shelver.
    Lève HTTPException(409) si le push échoue ou si devpod ssh échoue.
    """
    script_b64 = base64.b64encode(SHELVE_SCRIPT.strip().encode()).decode()
    cmd_str = f"echo {script_b64} | base64 -d | bash -l"
    cmd = [*devpod_bin, "ssh", ws_id, "--command", cmd_str]

    _log.info("workspace_shelve_start", ws_id=ws_id)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    rc = proc.returncode
    stdout = stdout_bytes.decode(errors="replace").strip()
    stderr = stderr_bytes.decode(errors="replace").strip()

    _log.info("workspace_shelve_done", ws_id=ws_id, rc=rc)

    if rc == 0:
        for line in stdout.splitlines():
            if line.strip() == "NOTHING_TO_SHELVE":
                return None
            if line.strip().startswith("SHELVED:"):
                branch = line.strip()[len("SHELVED:"):]
                _log.info("workspace_shelved", ws_id=ws_id, branch=branch)
                return branch
        # rc=0 mais sortie inattendue — dégradation gracieuse
        _log.warning("workspace_shelve_unexpected_output", ws_id=ws_id, stdout=stdout)
        return None

    _log.warning("workspace_shelve_failed", ws_id=ws_id, rc=rc, stderr=stderr[:500])
    detail = stderr.strip() or "Échec du push de la branche recovery"
    raise HTTPException(
        status_code=409,
        detail=f"Shelve impossible — suppression annulée. Détail : {detail}",
    )
```

- [ ] Créer le fichier avec le contenu ci-dessus

### Étape 1.3 — Vérifier que le test passe

```bash
cd backend && uv run pytest tests/devpod/test_shelve.py::test_shelve_nothing_to_shelve -v
```

Attendu : PASS

### Étape 1.4 — Ajouter les tests manquants dans test_shelve.py

```python
@pytest.mark.asyncio
async def test_shelve_returns_branch():
    proc = _make_proc(b"SHELVED:recovery-16-06-26-10-30\n", 0)
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await shelve_if_pending(["devpod"], "alice-myws", {})
    assert result == "recovery-16-06-26-10-30"


@pytest.mark.asyncio
async def test_shelve_push_failure_raises_409():
    proc = _make_proc(b"", 1)
    proc.communicate = AsyncMock(return_value=(b"", b"remote: Permission denied\n"))
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        with pytest.raises(HTTPException) as exc_info:
            await shelve_if_pending(["devpod"], "alice-myws", {})
    assert exc_info.value.status_code == 409
    assert "remote: Permission denied" in exc_info.value.detail


@pytest.mark.asyncio
async def test_shelve_not_a_git_repo_returns_none():
    # rc=0 + NOTHING_TO_SHELVE (le script détecte absence de .git)
    proc = _make_proc(b"NOTHING_TO_SHELVE\n", 0)
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await shelve_if_pending(["devpod"], "alice-myws", {})
    assert result is None


@pytest.mark.asyncio
async def test_shelve_passes_correct_command():
    """Le cmd devpod ssh contient bien ws_id et la commande base64."""
    proc = _make_proc(b"NOTHING_TO_SHELVE\n", 0)
    captured: list[tuple] = []

    async def fake_exec(*args, **kwargs):
        captured.append(args)
        return proc

    with patch("asyncio.create_subprocess_exec", fake_exec):
        await shelve_if_pending(["devpod"], "alice-myws", {})

    cmd = captured[0]
    assert cmd[0] == "devpod"
    assert cmd[1] == "ssh"
    assert cmd[2] == "alice-myws"
    assert cmd[3] == "--command"
    assert "base64 -d" in cmd[4]
```

- [ ] Ajouter les 4 tests ci-dessus dans `test_shelve.py`

```bash
cd backend && uv run pytest tests/devpod/test_shelve.py -v
```

Attendu : 5/5 PASS

### Étape 1.5 — Modifier `service.py` : import + `delete()` retourne dict

Ajouter l'import en tête du bloc d'imports locaux dans `service.py` :

```python
from .shelve import shelve_if_pending
```

Remplacer la méthode `delete` (actuellement lignes 262-279) par :

```python
async def delete(self, login: str, ws_id: str) -> dict[str, Any]:
    """Supprime un workspace (force). Shelve le travail en attente avant."""
    branch = await shelve_if_pending(self._devpod_bin, ws_id, self._minimal_env(login))
    await self._stop_port_forward(ws_id)
    if self._exposure is not None:
        try:
            await self._exposure.unexpose(ws_id)
        except Exception as exc:
            _log.warning("workspace_unexpose_failed", ws_id=ws_id, error=type(exc).__name__)
    env = self._minimal_env(login)
    cmd = [*self._devpod_bin, "delete", ws_id, "--force"]
    log_path = self._log_path(login, f"{ws_id}-delete")
    rc = await run_subprocess(cmd=cmd, env=env, log_path=log_path, ws_id=ws_id)
    if rc != 0:
        _log.warning("workspace_delete_failed", ws_id=ws_id, returncode=rc)
    status_path = self._status_path(ws_id)
    if status_path.exists():
        status_path.unlink()
    _log.info("workspace_deleted", ws_id=ws_id, login=login, recovery_branch=branch)
    return {"deleted": True, "recovery_branch": branch}
```

- [ ] Ajouter l'import `from .shelve import shelve_if_pending` dans `service.py`
- [ ] Remplacer `delete()` avec la version ci-dessus

### Étape 1.6 — Modifier `workspace_ops.py` : retourner recovery_branch

Remplacer l'endpoint `workspace_delete` (lignes 288-297) par :

```python
@router.post("/workspaces/{name}/delete")
async def workspace_delete(
    name: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, Any]:
    _validate_name(name)
    ws_id = f"{user.login}-{name}"
    svc = _get_service()
    result = await svc.delete(login=user.login, ws_id=ws_id)
    return {"ws_id": ws_id, **result}
```

- [ ] Remplacer `workspace_delete` dans `workspace_ops.py`

### Étape 1.7 — Lancer la suite de tests complète

```bash
cd backend && uv run pytest tests/ -v --tb=short 2>&1 | tail -20
```

Attendu : tous les tests existants passent (rétrocompat OK).

### Étape 1.8 — Lint + mypy

```bash
cd backend && uv run ruff check src/portal/devpod/shelve.py src/portal/devpod/service.py src/portal/routes/workspace_ops.py
cd backend && uv run mypy src/portal/devpod/shelve.py src/portal/devpod/service.py
```

Attendu : 0 erreur.

### Étape 1.9 — Commit

```bash
git add backend/src/portal/devpod/shelve.py \
        backend/src/portal/devpod/service.py \
        backend/src/portal/routes/workspace_ops.py \
        backend/tests/devpod/__init__.py \
        backend/tests/devpod/test_shelve.py
git commit -m "feat(workspace): shelve le travail en cours avant suppression

Lance devpod ssh --command avec un script bash qui détecte le travail
en attente (WIP + commits non poussés), crée une branche recovery-*
et la pousse avant la suppression. 409 si le push échoue.
L'endpoint /delete retourne recovery_branch dans la réponse."
```

---

## Task 2 : Tests d'intégration backend — endpoint /delete avec shelve

**Files:**
- Modify: `backend/tests/routes/test_workspace_ops.py`

### Étape 2.1 — Trouver les tests de delete existants

Lire `backend/tests/routes/test_workspace_ops.py` et chercher le test de `workspace_delete`. Identifier comment `DevPodService.delete` est mockée.

### Étape 2.2 — Écrire les tests rouges

Ajouter dans `test_workspace_ops.py` (importer `shelve_if_pending` et `AsyncMock` si pas déjà présents) :

```python
# Dans le bloc d'imports en haut du fichier (si pas déjà présents) :
# from unittest.mock import AsyncMock, patch

def test_delete_nothing_to_shelve_returns_no_branch(client_alice):
    """Suppression normale — recovery_branch absent de la réponse."""
    with patch(
        "portal.devpod.shelve.shelve_if_pending",
        AsyncMock(return_value=None),
    ):
        resp = client_alice.post("/me/workspaces/myws/delete")
    assert resp.status_code == 200
    data = resp.json()
    assert data["deleted"] is True
    assert data["recovery_branch"] is None


def test_delete_shelved_returns_branch(client_alice):
    """Suppression avec shelve — recovery_branch dans la réponse."""
    with patch(
        "portal.devpod.shelve.shelve_if_pending",
        AsyncMock(return_value="recovery-16-06-26-10-30"),
    ):
        resp = client_alice.post("/me/workspaces/myws/delete")
    assert resp.status_code == 200
    data = resp.json()
    assert data["recovery_branch"] == "recovery-16-06-26-10-30"


def test_delete_push_failure_returns_409(client_alice):
    """Push échoue → 409, workspace non supprimé."""
    from fastapi import HTTPException

    with patch(
        "portal.devpod.shelve.shelve_if_pending",
        AsyncMock(side_effect=HTTPException(409, "Shelve impossible")),
    ):
        resp = client_alice.post("/me/workspaces/myws/delete")
    assert resp.status_code == 409
```

Note : regarde comment les autres tests de `test_workspace_ops.py` configurent `client_alice` et mockent DevPodService. Adapte le nom de la fixture si différent.

- [ ] Ajouter les 3 tests ci-dessus dans `test_workspace_ops.py`

```bash
cd backend && uv run pytest tests/routes/test_workspace_ops.py -k "test_delete" -v
```

Attendu : les nouveaux tests passent (les mocks interceptent avant l'appel réseau).

### Étape 2.3 — Suite complète

```bash
cd backend && uv run pytest tests/ -q 2>&1 | tail -5
```

Attendu : tous les tests passent.

### Étape 2.4 — Commit

```bash
git add backend/tests/routes/test_workspace_ops.py
git commit -m "test(workspace): couvrir delete avec shelve (NOTHING_TO_SHELVE, SHELVED, 409)"
```

---

## Task 3 : Frontend — useWorkspaceOps.ts + WorkspaceCard.tsx + i18n

**Files:**
- Modify: `frontend/src/features/workspaces/useWorkspaceOps.ts`
- Modify: `frontend/src/features/workspaces/WorkspaceCard.tsx`
- Modify: `frontend/src/i18n/en.json`
- Modify: `frontend/src/i18n/fr.json`

### Étape 3.1 — Ajouter les clés i18n

Dans `frontend/src/i18n/en.json`, section `workspaces.confirm` — ajouter après `"cancel"` :

```json
"deleteShelveHint": "Any uncommitted work will be pushed to a recovery branch before deletion.",
"recoverySaved": "Work saved to branch {{branch}}."
```

Dans `frontend/src/i18n/fr.json`, section `workspaces.confirm` — ajouter après `"cancel"` :

```json
"deleteShelveHint": "Tout travail non committé sera poussé sur une branche recovery avant la suppression.",
"recoverySaved": "Travail sauvegardé sur la branche {{branch}}."
```

- [ ] Ajouter les 2 clés EN dans `en.json`
- [ ] Ajouter les 2 clés FR dans `fr.json`

### Étape 3.2 — Modifier `useWorkspaceOps.ts`

Ajouter l'import `useTranslation` :

```ts
import { useTranslation } from 'react-i18next'
```

Dans le corps de `useWorkspaceOps()`, avant les mutations :

```ts
const { t } = useTranslation()
```

Remplacer la mutation `deleteWorkspace` par :

```ts
const deleteWorkspace = useMutation<
  { deleted: boolean; recovery_branch: string | null },
  Error,
  string
>({
  mutationFn: async (name: string) => {
    const result = await apiFetchJson<{
      deleted: boolean
      recovery_branch: string | null
    }>(`/me/workspaces/${name}/delete`, { method: 'POST' })
    await apiFetch(`/me/workspaces/${name}`, { method: 'DELETE' })
    return result
  },
  onSuccess: (data) => {
    qc.invalidateQueries({ queryKey: ['workspaces'] })
    if (data.recovery_branch) {
      toast.success(t('workspaces.confirm.recoverySaved', { branch: data.recovery_branch }))
    }
  },
  onError: (err: Error) => {
    // apiFetchJson lève ApiError(status, text) — text peut être {"detail": "..."}
    let msg = err.message
    try {
      const parsed: unknown = JSON.parse(err.message)
      if (parsed && typeof parsed === 'object' && 'detail' in parsed) {
        msg = String((parsed as { detail: unknown }).detail)
      }
    } catch {
      // message n'est pas du JSON, on l'utilise tel quel
    }
    toast.error(msg)
  },
})
```

- [ ] Ajouter `import { useTranslation } from 'react-i18next'`
- [ ] Ajouter `const { t } = useTranslation()` dans le corps de la fonction
- [ ] Remplacer `deleteWorkspace` avec la version ci-dessus

### Étape 3.3 — Modifier `WorkspaceCard.tsx` — ajout dialog de confirmation

Ajouter les imports en tête :

```tsx
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
```

Ajouter l'état interne après les états existants (`sshKeyOpen`, `logsOpen`) :

```tsx
const [confirmOpen, setConfirmOpen] = useState(false)
```

Dans la section boutons, modifier le bouton "Supprimer" pour ouvrir le dialog au lieu d'appeler `onDelete` directement. Le bouton est actuellement :

```tsx
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
```

Remplacer par :

```tsx
{(s === 'stopped' || s === 'unknown' || s === 'failed') && (
  <Button
    size="sm"
    variant="ghost"
    className="text-destructive hover:text-destructive"
    onClick={() => setConfirmOpen(true)}
  >
    {t('workspaces.actions.delete')}
  </Button>
)}
```

Ajouter le Dialog de confirmation juste avant la fermeture `</div>` finale du composant (après `</LogDialog>`) :

```tsx
<Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
  <DialogContent className="sm:max-w-md">
    <DialogHeader>
      <DialogTitle>{t('workspaces.confirm.deleteTitle')}</DialogTitle>
      <DialogDescription className="space-y-2">
        <span>{t('workspaces.confirm.deleteDescription', { name: spec.name })}</span>
        {' '}
        <span>{t('workspaces.confirm.deleteShelveHint')}</span>
      </DialogDescription>
    </DialogHeader>
    <DialogFooter>
      <Button variant="ghost" size="sm" onClick={() => setConfirmOpen(false)}>
        {t('workspaces.confirm.cancel')}
      </Button>
      <Button
        variant="destructive"
        size="sm"
        onClick={() => {
          setConfirmOpen(false)
          onDelete(spec.name)
        }}
      >
        {t('workspaces.confirm.confirm')}
      </Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
```

- [ ] Ajouter les imports Dialog
- [ ] Ajouter `const [confirmOpen, setConfirmOpen] = useState(false)`
- [ ] Modifier le bouton Supprimer pour ouvrir le dialog
- [ ] Ajouter le `<Dialog>` de confirmation en fin de composant

### Étape 3.4 — Vérifier TypeScript

```bash
cd frontend && npx tsc --noEmit 2>&1
```

Attendu : 0 erreur.

### Étape 3.5 — Commit

```bash
git add \
  frontend/src/features/workspaces/useWorkspaceOps.ts \
  frontend/src/features/workspaces/WorkspaceCard.tsx \
  frontend/src/i18n/en.json \
  frontend/src/i18n/fr.json
git commit -m "feat(workspace): dialog de confirmation suppression + toast branche recovery

Ajoute un dialog de confirmation avant la suppression avec avertissement
shelve. Toast success si recovery_branch présent dans la réponse.
Toast erreur si 409 (push échoué, workspace non supprimé). i18n FR+EN."
```

---

## Checklist finale (Definition of Done)

- [ ] `portal/devpod/shelve.py` : SHELVE_SCRIPT + `shelve_if_pending()` avec cas `not a git repo`
- [ ] `service.delete()` : appelle shelve avant delete, retourne `{"deleted": True, "recovery_branch": branch}`
- [ ] `workspace_delete` endpoint retourne `recovery_branch`
- [ ] 409 si push échoue (workspace non supprimé)
- [ ] Tests backend : 5 tests shelve + 3 tests endpoint delete → tous verts
- [ ] `useWorkspaceOps.deleteWorkspace` : recovery toast si `recovery_branch`, parsing JSON detail pour 409
- [ ] `WorkspaceCard` : dialog de confirmation avec hint shelve
- [ ] i18n FR + EN : `deleteShelveHint`, `recoverySaved`
- [ ] `ruff check` + `mypy` OK sur les fichiers modifiés
- [ ] `tsc --noEmit` OK
- [ ] Aucun secret dans le diff
- [ ] Commits conventionnels FR sur `dev`
