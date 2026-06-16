# Edit Git Credentials — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre l'édition complète d'un credential git (nom, host, kind, username, secret) via un bouton crayon qui ouvre un dialog.

**Architecture:** PATCH `/me/git-credentials/{name}` côté backend (cascade rename sur workspaces) ; hook `useUpdateGitCredential` côté frontend ; dialog d'édition dans `GitCredentialManager` avec champs pré-remplis et secret masqué.

**Tech Stack:** FastAPI + Pydantic v2 (backend) ; TanStack Query v5 + React 19 + Radix Dialog (frontend)

---

## Fichiers concernés

| Fichier | Action |
|---------|--------|
| `backend/src/portal/routes/me.py` | Ajouter `_GitCredentialUpdate` + `patch_git_credential` + exposer `username` dans GET |
| `backend/tests/routes/test_me.py` | Ajouter tests pour GET username + PATCH (8 cas) |
| `frontend/src/features/git-credentials/useGitCredentials.ts` | Ajouter `UpdateCredentialPayload` + `useUpdateGitCredential` + `username` dans `GitCredentialSummary` |
| `frontend/src/features/git-credentials/GitCredentialManager.tsx` | Ajouter bouton Pencil, état d'édition, dialog |
| `frontend/src/i18n/fr.json` | Ajouter clés `edit`, `editDialogTitle` |
| `frontend/src/i18n/en.json` | Idem en anglais |

---

## Task 1 — Backend : exposer `username` dans GET /me/git-credentials

**Files:**
- Modify: `backend/src/portal/routes/me.py:118-126`
- Test: `backend/tests/routes/test_me.py`

- [ ] **Étape 1 : Écrire le test qui échoue**

Ajouter en bas de `backend/tests/routes/test_me.py` :

```python
def test_get_git_credentials_includes_username(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        client.post("/me/git-credentials", json={
            "name": "gh", "host": "github.com", "kind": "token",
            "username": "oauth2", "token": "ghp_test123",
        })
        resp = client.get("/me/git-credentials")
    assert resp.status_code == 200
    creds = resp.json()
    assert len(creds) == 1
    assert creds[0]["username"] == "oauth2"
```

- [ ] **Étape 2 : Vérifier que le test échoue**

```bash
cd backend && uv run pytest tests/routes/test_me.py::test_get_git_credentials_includes_username -v
```

Attendu : `FAILED` — `KeyError: 'username'`

- [ ] **Étape 3 : Implémenter**

Dans `backend/src/portal/routes/me.py`, remplacer la compréhension du GET :

```python
@router.get("/git-credentials")
async def list_git_credentials(
    user: UserInfo = Depends(require_user),
) -> list[dict[str, object]]:
    cfg = load_user(user.login)
    return [
        {"name": c.name, "host": c.host, "kind": c.kind, "username": c.username}
        for c in cfg.git_credentials
    ]
```

- [ ] **Étape 4 : Vérifier que le test passe**

```bash
cd backend && uv run pytest tests/routes/test_me.py::test_get_git_credentials_includes_username -v
```

Attendu : `PASSED`

- [ ] **Étape 5 : Commit**

```bash
git add backend/src/portal/routes/me.py backend/tests/routes/test_me.py
git commit -m "feat: expose username dans GET /me/git-credentials"
```

---

## Task 2 — Backend : PATCH /me/git-credentials/{name}

**Files:**
- Modify: `backend/src/portal/routes/me.py`
- Test: `backend/tests/routes/test_me.py`

- [ ] **Étape 1 : Écrire les 8 tests qui échouent**

Ajouter à la suite de `test_me.py` :

```python
# ── helpers ────────────────────────────────────────────────────────────────

_FAKE_SSH_KEY = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "dGVzdC1rZXktZm9yLXRlc3Rpbmctb25seQ==\n"
    "-----END OPENSSH PRIVATE KEY-----"
)


def _add_token_cred(client: TestClient, name: str = "gh") -> None:
    client.post("/me/git-credentials", json={
        "name": name, "host": "github.com", "kind": "token",
        "username": "oauth2", "token": "ghp_old",
    })


def _add_ssh_cred(client: TestClient, name: str = "gl-ssh") -> None:
    client.post("/me/git-credentials", json={
        "name": name, "host": "gitlab.com", "kind": "ssh",
        "private_key": _FAKE_SSH_KEY,
    })


# ── PATCH tests ─────────────────────────────────────────────────────────────

def test_patch_git_credential_updates_host(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        _add_token_cred(client)
        resp = client.patch("/me/git-credentials/gh", json={"host": "github.enterprise.com"})
    assert resp.status_code == 200
    assert resp.json()["host"] == "github.enterprise.com"
    with TestClient(app) as client:
        creds = client.get("/me/git-credentials").json()
    assert creds[0]["host"] == "github.enterprise.com"


def test_patch_git_credential_updates_token(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        _add_token_cred(client)
        resp = client.patch("/me/git-credentials/gh", json={"token": "ghp_new"})
    assert resp.status_code == 200
    from portal.config.store import load_user
    cfg = load_user("alice")
    assert cfg.git_credentials[0].token == "ghp_new"


def test_patch_git_credential_unchanged_token_preserved(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        _add_token_cred(client)
        resp = client.patch("/me/git-credentials/gh", json={"token": "__UNCHANGED__"})
    assert resp.status_code == 200
    from portal.config.store import load_user
    cfg = load_user("alice")
    assert cfg.git_credentials[0].token == "ghp_old"


def test_patch_git_credential_token_to_ssh(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        _add_token_cred(client)
        resp = client.patch("/me/git-credentials/gh", json={
            "kind": "ssh", "private_key": _FAKE_SSH_KEY,
        })
    assert resp.status_code == 200
    from portal.config.store import load_user
    cfg = load_user("alice")
    cred = cfg.git_credentials[0]
    assert cred.kind == "ssh"
    assert cred.token == ""
    assert cred.key_path != ""


def test_patch_git_credential_ssh_to_token(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        _add_ssh_cred(client)
        resp = client.patch("/me/git-credentials/gl-ssh", json={
            "kind": "token", "token": "glpat-new",
        })
    assert resp.status_code == 200
    from portal.config.store import load_user
    cfg = load_user("alice")
    cred = cfg.git_credentials[0]
    assert cred.kind == "token"
    assert cred.token == "glpat-new"
    assert cred.key_path == ""


def test_patch_git_credential_rename_cascades_workspaces(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        _add_token_cred(client, name="gh")
        client.post("/me/workspaces", json={
            "name": "myapp",
            "source": "github.com/org/repo",
            "git_credential": "gh",
        })
        resp = client.patch("/me/git-credentials/gh", json={"new_name": "github"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "github"
    with TestClient(app) as client:
        ws_list = client.get("/me/workspaces").json()
    assert ws_list[0]["git_credential"] == "github"


def test_patch_git_credential_duplicate_name_returns_409(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        _add_token_cred(client, name="gh")
        _add_token_cred(client, name="gh2")
        resp = client.patch("/me/git-credentials/gh", json={"new_name": "gh2"})
    assert resp.status_code == 409


def test_patch_git_credential_not_found_returns_404(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.patch("/me/git-credentials/nope", json={"host": "example.com"})
    assert resp.status_code == 404
```

- [ ] **Étape 2 : Vérifier que les tests échouent**

```bash
cd backend && uv run pytest tests/routes/test_me.py -k "patch_git_credential" -v
```

Attendu : 8× `FAILED` — `405 Method Not Allowed`

- [ ] **Étape 3 : Implémenter le modèle et l'endpoint**

Dans `backend/src/portal/routes/me.py`, ajouter **après** la classe `_GitCredentialCreate` et avant le handler DELETE (vers la ligne 175) :

```python
class _GitCredentialUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_name: str | None = None
    host: str | None = None
    kind: Literal["ssh", "token"] | None = None
    username: str | None = None
    token: str | None = None
    private_key: str | None = None


@router.patch("/git-credentials/{name}")
async def patch_git_credential(
    name: str,
    body: _GitCredentialUpdate,
    user: UserInfo = Depends(require_user),
) -> dict[str, object]:
    cfg = load_user(user.login)
    cred = next((c for c in cfg.git_credentials if c.name == name), None)
    if not cred:
        raise HTTPException(status_code=404, detail=f"Credential {name!r} not found")

    if body.new_name is not None:
        if not _CRED_NAME_RE.fullmatch(body.new_name):
            raise HTTPException(status_code=422, detail=f"Invalid credential name: {body.new_name!r}")
        if body.new_name != name and any(c.name == body.new_name for c in cfg.git_credentials):
            raise HTTPException(status_code=409, detail=f"Credential {body.new_name!r} already exists")

    effective_kind = body.kind if body.kind is not None else cred.kind
    effective_name = body.new_name if body.new_name is not None else name
    effective_host = (
        body.host.strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
        if body.host is not None else cred.host
    )
    effective_username = body.username.strip() if body.username is not None else cred.username

    new_key_path = cred.key_path
    new_token = cred.token

    if effective_kind == "ssh":
        new_token = ""
        if body.private_key is None or body.private_key == "__UNCHANGED__":
            if cred.kind != "ssh":
                raise HTTPException(
                    status_code=422, detail="private_key is required when changing kind to ssh"
                )
        else:
            old_key_path = cred.key_path
            key_dir = safe_user_path(user.login, "keys", "git", effective_name)
            key_dir.mkdir(parents=True, exist_ok=True)
            key_file = key_dir / "id_ed25519"
            key_file.write_text(body.private_key.strip() + "\n", encoding="utf-8")
            key_file.chmod(0o600)
            new_key_path = str(key_file)
            if old_key_path and old_key_path != new_key_path:
                old = Path(old_key_path)
                if old.exists():
                    old.unlink()
    else:
        new_key_path = ""
        if body.token is None or body.token == "__UNCHANGED__":
            if cred.kind != "token":
                raise HTTPException(
                    status_code=422, detail="token is required when changing kind to token"
                )
            new_token = cred.token
        else:
            if not body.token.strip():
                raise HTTPException(status_code=422, detail="token cannot be empty")
            new_token = body.token.strip()
        if cred.kind == "ssh" and cred.key_path:
            old = Path(cred.key_path)
            if old.exists():
                old.unlink()

    updated = GitCredential(
        name=effective_name,
        host=effective_host,
        kind=effective_kind,
        key_path=new_key_path,
        username=effective_username,
        token=new_token,
    )
    cfg.git_credentials = [updated if c.name == name else c for c in cfg.git_credentials]

    if effective_name != name:
        for ws in cfg.workspaces:
            if ws.git_credential == name:
                ws.git_credential = effective_name
            for src in ws.extra_sources:
                if src.git_credential == name:
                    src.git_credential = effective_name

    save_user(user.login, cfg)
    _log.info("git_credential_updated", login=user.login, name=name, new_name=effective_name)
    return {"name": effective_name, "host": effective_host, "kind": effective_kind}
```

- [ ] **Étape 4 : Vérifier que tous les tests passent**

```bash
cd backend && uv run pytest tests/routes/test_me.py -k "patch_git_credential or get_git_credentials" -v
```

Attendu : 9× `PASSED` (8 PATCH + 1 GET username)

- [ ] **Étape 5 : Suite complète**

```bash
cd backend && uv run pytest -v
```

Attendu : tous passent

- [ ] **Étape 6 : Lint + mypy**

```bash
cd backend && uv run ruff check src/ tests/ && uv run ruff format src/ tests/ && uv run mypy src/
```

- [ ] **Étape 7 : Commit**

```bash
git add backend/src/portal/routes/me.py backend/tests/routes/test_me.py
git commit -m "feat: PATCH /me/git-credentials/{name} avec cascade rename workspaces"
```

---

## Task 3 — Frontend : type + hook useUpdateGitCredential

**Files:**
- Modify: `frontend/src/features/git-credentials/useGitCredentials.ts`

- [ ] **Étape 1 : Mettre à jour le fichier**

Remplacer le contenu complet de `frontend/src/features/git-credentials/useGitCredentials.ts` par :

```typescript
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson, apiFetch } from '@/shared/api/client'

export interface GitCredentialSummary {
  name: string
  host: string
  kind: 'ssh' | 'token'
  username: string
}

interface AddCredentialPayload {
  name: string
  host: string
  kind: 'ssh' | 'token'
  username?: string
  token?: string
  private_key?: string
}

export interface UpdateCredentialPayload {
  new_name?: string
  host?: string
  kind?: 'ssh' | 'token'
  username?: string
  token?: string         // "__UNCHANGED__" pour conserver l'existant
  private_key?: string   // "__UNCHANGED__" pour conserver l'existant
}

const QK = ['git-credentials'] as const

export function useGitCredentials() {
  return useQuery<GitCredentialSummary[]>({
    queryKey: QK,
    queryFn: () => apiFetchJson<GitCredentialSummary[]>('/me/git-credentials'),
  })
}

export function useAddGitCredential() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: AddCredentialPayload) =>
      apiFetchJson<GitCredentialSummary>('/me/git-credentials', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  })
}

export function useUpdateGitCredential() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, payload }: { name: string; payload: UpdateCredentialPayload }) =>
      apiFetchJson<GitCredentialSummary>(
        `/me/git-credentials/${encodeURIComponent(name)}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  })
}

export function useDeleteGitCredential() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) =>
      apiFetch(`/me/git-credentials/${encodeURIComponent(name)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  })
}
```

- [ ] **Étape 2 : Vérifier que TypeScript compile**

```bash
cd frontend && npx tsc --noEmit
```

Attendu : aucune erreur

- [ ] **Étape 3 : Commit**

```bash
git add frontend/src/features/git-credentials/useGitCredentials.ts
git commit -m "feat: hook useUpdateGitCredential + username dans GitCredentialSummary"
```

---

## Task 4 — Frontend : i18n

**Files:**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Étape 1 : Ajouter les clés françaises**

Dans `frontend/src/i18n/fr.json`, dans l'objet `gitCredentials`, ajouter après la clé `"add"` :

```json
"edit": "Modifier",
"editDialogTitle": "Modifier le credential",
```

- [ ] **Étape 2 : Ajouter les clés anglaises**

Dans `frontend/src/i18n/en.json`, dans l'objet `gitCredentials`, ajouter après la clé `"add"` :

```json
"edit": "Edit",
"editDialogTitle": "Edit credential",
```

- [ ] **Étape 3 : Commit**

```bash
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat: clés i18n pour édition credential"
```

---

## Task 5 — Frontend : dialog d'édition dans GitCredentialManager

**Files:**
- Modify: `frontend/src/features/git-credentials/GitCredentialManager.tsx`

- [ ] **Étape 1 : Remplacer les imports**

En haut du fichier, remplacer la ligne `import { Plus, Trash2, KeyRound, Eye, EyeOff } from 'lucide-react'` par :

```typescript
import { Plus, Trash2, KeyRound, Eye, EyeOff, Pencil } from 'lucide-react'
```

Remplacer l'import du hook :

```typescript
import {
  useGitCredentials,
  useAddGitCredential,
  useDeleteGitCredential,
  useUpdateGitCredential,
  type GitCredentialSummary,
  type UpdateCredentialPayload,
} from './useGitCredentials'
```

- [ ] **Étape 2 : Ajouter l'état d'édition et les helpers**

Après la constante `EMPTY_FORM`, ajouter :

```typescript
const SENTINEL = '••••••••'

type EditFormState = {
  name: string
  hostSelect: KnownHostValue
  hostCustom: string
  kind: 'ssh' | 'token'
  username: string
  tokenValue: string
  tokenTouched: boolean
  privateKey: string
  keyTouched: boolean
}

function toHostSelect(host: string): KnownHostValue {
  const known = KNOWN_HOSTS.find(h => h.value !== '__other__' && h.value === host)
  return known ? known.value as KnownHostValue : '__other__'
}

function initEditForm(c: GitCredentialSummary): EditFormState {
  return {
    name: c.name,
    hostSelect: toHostSelect(c.host),
    hostCustom: c.host,
    kind: c.kind,
    username: c.username,
    tokenValue: SENTINEL,
    tokenTouched: false,
    privateKey: '',
    keyTouched: false,
  }
}
```

- [ ] **Étape 3 : Ajouter les états et le hook dans le composant**

Dans `GitCredentialManager`, après la ligne `const deleteMutation = useDeleteGitCredential()`, ajouter :

```typescript
const updateMutation = useUpdateGitCredential()

const [toEdit, setToEdit] = useState<GitCredentialSummary | null>(null)
const [editForm, setEditForm] = useState<EditFormState | null>(null)
const [editError, setEditError] = useState('')
```

- [ ] **Étape 4 : Ajouter la fonction handleEditSubmit**

Après la fonction `handleDelete`, ajouter :

```typescript
function openEdit(c: GitCredentialSummary) {
  setToEdit(c)
  setEditForm(initEditForm(c))
  setEditError('')
}

function closeEdit() {
  setToEdit(null)
  setEditForm(null)
  setEditError('')
}

function handleEditKindChange(newKind: 'ssh' | 'token') {
  setEditForm(f => f ? {
    ...f,
    kind: newKind,
    tokenValue: '',
    tokenTouched: newKind === 'token',
    privateKey: '',
    keyTouched: newKind === 'ssh',
  } : f)
}

function handleEditSubmit(e: FormEvent) {
  e.preventDefault()
  if (!toEdit || !editForm) return
  setEditError('')

  const effectiveHost =
    editForm.hostSelect === '__other__' ? editForm.hostCustom.trim() : editForm.hostSelect

  const payload: UpdateCredentialPayload = {
    host: effectiveHost,
    kind: editForm.kind,
    username: editForm.username,
  }
  if (editForm.name !== toEdit.name) payload.new_name = editForm.name
  if (editForm.kind === 'token') {
    payload.token = editForm.tokenTouched ? editForm.tokenValue : '__UNCHANGED__'
  } else {
    payload.private_key = editForm.keyTouched ? editForm.privateKey : '__UNCHANGED__'
  }

  updateMutation.mutate(
    { name: toEdit.name, payload },
    {
      onSuccess: () => closeEdit(),
      onError: (err: unknown) =>
        setEditError(err instanceof Error ? err.message : t('gitCredentials.errors.update')),
    },
  )
}
```

- [ ] **Étape 5 : Ajouter le bouton Pencil dans la liste**

Trouver le bloc du bouton `Trash2` dans la liste de credentials et ajouter le bouton Pencil juste avant :

```tsx
<Button
  size="icon"
  variant="ghost"
  className="h-8 w-8"
  onClick={() => openEdit(c)}
  aria-label={t('gitCredentials.edit')}
>
  <Pencil className="h-4 w-4" />
</Button>
<Button
  size="icon"
  variant="ghost"
  className="h-8 w-8 text-destructive hover:text-destructive"
  onClick={() => setToDelete(c)}
  aria-label={t('gitCredentials.delete')}
>
  <Trash2 className="h-4 w-4" />
</Button>
```

- [ ] **Étape 6 : Ajouter le dialog d'édition**

Après le dialog de confirmation de suppression (à la fin du return, avant la fermeture `</div>`), ajouter :

```tsx
{/* ── Dialog d'édition ────────────────────────────────────────── */}
<Dialog open={!!toEdit} onOpenChange={open => { if (!open) closeEdit() }}>
  <DialogContent>
    <DialogHeader>
      <DialogTitle>{t('gitCredentials.editDialogTitle')}</DialogTitle>
    </DialogHeader>

    {editForm && (
      <form onSubmit={handleEditSubmit} className="flex flex-col gap-4 pt-2">
        {/* Nom */}
        <div>
          <Label htmlFor="edit-cred-name" className="text-xs">{t('gitCredentials.name')}</Label>
          <Input
            id="edit-cred-name"
            value={editForm.name}
            onChange={e => setEditForm(f => f ? { ...f, name: e.target.value } : f)}
            className="mt-1"
            required
          />
        </div>

        {/* Hôte */}
        <div>
          <Label className="text-xs">{t('gitCredentials.host')}</Label>
          <Select
            value={editForm.hostSelect}
            onValueChange={v => setEditForm(f => f ? { ...f, hostSelect: v as KnownHostValue } : f)}
          >
            <SelectTrigger className="mt-1">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {KNOWN_HOSTS.map(h => (
                <SelectItem key={h.value} value={h.value}>
                  {t(h.labelKey)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {editForm.hostSelect === '__other__' && (
            <Input
              value={editForm.hostCustom}
              onChange={e => setEditForm(f => f ? { ...f, hostCustom: e.target.value } : f)}
              placeholder="git.example.com"
              className="mt-2"
              required
            />
          )}
        </div>

        {/* Type */}
        <div>
          <Label className="text-xs">{t('gitCredentials.kind')}</Label>
          <Select
            value={editForm.kind}
            onValueChange={v => handleEditKindChange(v as 'ssh' | 'token')}
          >
            <SelectTrigger className="mt-1">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="token">{t('gitCredentials.kindPat')}</SelectItem>
              <SelectItem value="ssh">{t('gitCredentials.kindSsh')}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Champs PAT */}
        {editForm.kind === 'token' && (
          <>
            <div>
              <Label htmlFor="edit-cred-username" className="text-xs">
                {t('gitCredentials.username')}
              </Label>
              <Input
                id="edit-cred-username"
                value={editForm.username}
                onChange={e => setEditForm(f => f ? { ...f, username: e.target.value } : f)}
                placeholder={t('gitCredentials.usernamePlaceholder')}
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="edit-cred-token" className="text-xs">
                {t('gitCredentials.token')}
              </Label>
              <div className="relative mt-1">
                <Input
                  id="edit-cred-token"
                  type={showToken ? 'text' : 'password'}
                  value={editForm.tokenValue}
                  onFocus={() => {
                    if (!editForm.tokenTouched) {
                      setEditForm(f => f ? { ...f, tokenValue: '' } : f)
                    }
                  }}
                  onChange={e =>
                    setEditForm(f => f ? { ...f, tokenValue: e.target.value, tokenTouched: true } : f)
                  }
                  onBlur={() => {
                    if (!editForm.tokenTouched || editForm.tokenValue === '') {
                      setEditForm(f => f ? { ...f, tokenValue: SENTINEL, tokenTouched: false } : f)
                    }
                  }}
                  className="pr-9"
                />
                <button
                  type="button"
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  onClick={() => setShowToken(v => !v)}
                  tabIndex={-1}
                >
                  {showToken ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>
          </>
        )}

        {/* Champ SSH */}
        {editForm.kind === 'ssh' && (
          <div>
            <Label htmlFor="edit-cred-key" className="text-xs">
              {t('gitCredentials.privateKey')}
            </Label>
            <Textarea
              id="edit-cred-key"
              value={editForm.privateKey}
              onChange={e =>
                setEditForm(f => f ? { ...f, privateKey: e.target.value, keyTouched: e.target.value !== '' } : f)
              }
              placeholder={t('gitCredentials.privateKeyPlaceholder')}
              className="mt-1 font-mono text-xs"
              rows={6}
            />
            {!editForm.keyTouched && (
              <p className="mt-1 text-xs text-muted-foreground">
                {t('gitCredentials.sshKeyUnchangedHint')}
              </p>
            )}
          </div>
        )}

        {editError && (
          <p role="alert" className="text-xs text-destructive">{editError}</p>
        )}

        <DialogFooter>
          <Button type="button" variant="ghost" size="sm" onClick={closeEdit}>
            {t('gitCredentials.cancel')}
          </Button>
          <Button type="submit" size="sm" disabled={updateMutation.isPending}>
            {updateMutation.isPending ? '…' : t('gitCredentials.save')}
          </Button>
        </DialogFooter>
      </form>
    )}
  </DialogContent>
</Dialog>
```

- [ ] **Étape 7 : Ajouter les clés i18n manquantes**

`errors.load` et `errors.add` existent déjà dans les deux fichiers — ajouter uniquement `sshKeyUnchangedHint` et `errors.update`.

Dans `frontend/src/i18n/fr.json`, dans `gitCredentials` :
- Ajouter `"sshKeyUnchangedHint": "Laisser vide pour conserver la clé existante"` au niveau racine de `gitCredentials`
- Ajouter `"update": "Impossible de mettre à jour le credential."` dans l'objet `errors` existant (après `"delete"`)

Dans `frontend/src/i18n/en.json`, dans `gitCredentials` :
- Ajouter `"sshKeyUnchangedHint": "Leave empty to keep the existing key"` au niveau racine de `gitCredentials`
- Ajouter `"update": "Failed to update credential."` dans l'objet `errors` existant (après `"delete"`)

- [ ] **Étape 8 : Vérifier que TypeScript compile**

```bash
cd frontend && npx tsc --noEmit
```

Attendu : aucune erreur

- [ ] **Étape 9 : Commit**

```bash
git add frontend/src/features/git-credentials/GitCredentialManager.tsx \
        frontend/src/i18n/fr.json \
        frontend/src/i18n/en.json
git commit -m "feat: dialog d'édition de credential git"
```

---

## Task 6 — Vérification finale

- [ ] **Suite de tests backend complète**

```bash
cd backend && uv run pytest -v
```

Attendu : tous passent (370+ tests)

- [ ] **TypeScript frontend**

```bash
cd frontend && npx tsc --noEmit
```

Attendu : 0 erreur

- [ ] **Build frontend**

```bash
cd frontend && npm run build
```

Attendu : build sans erreur
