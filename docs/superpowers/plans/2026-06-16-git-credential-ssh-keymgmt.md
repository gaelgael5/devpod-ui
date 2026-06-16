# SSH Key Management — Git Credentials Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter le chargement de clé depuis un fichier, l'affichage de la clé publique et la génération Ed25519 côté serveur aux credentials git SSH.

**Architecture:** Deux nouvelles fonctions dans `ssh_keys.py` (`generate_git_credential_ssh_key`, `derive_git_credential_public_key`) ; la clé publique est stockée en `id_ed25519.pub` à côté de la clé privée ; le backend expose un GET endpoint `/public-key` ; le frontend ajoute un bouton d'upload, un bouton "Générer" (crée le credential + affiche la clé publique en dialog) et une icône clé sur chaque ligne SSH de la liste.

**Tech Stack:** Python 3.12 + FastAPI + Pydantic v2 + `cryptography` (backend) ; React 18 + TypeScript strict + TanStack Query v5 + shadcn/ui + i18next (frontend)

---

## Fichiers touchés

| Fichier | Action |
|---------|--------|
| `backend/src/portal/ssh_keys.py` | Modifier — 2 nouvelles fonctions + import `load_ssh_private_key` |
| `backend/src/portal/routes/me.py` | Modifier — champ `generate_key`, logique POST, nouveau GET endpoint, PATCH dérive `.pub` |
| `backend/tests/test_ssh_keys.py` | Créer — tests unitaires des 2 nouvelles fonctions |
| `backend/tests/routes/test_me.py` | Modifier — 7 nouveaux tests d'intégration |
| `frontend/src/features/git-credentials/useGitCredentials.ts` | Modifier — `public_key?`, `generate_key?`, hook `useGitCredentialPublicKey` |
| `frontend/src/features/git-credentials/GitCredentialPublicKeyDialog.tsx` | Créer — dialog clé publique avec copie |
| `frontend/src/features/git-credentials/GitCredentialManager.tsx` | Modifier — upload, génération, bouton clé publique par ligne, dialog |
| `frontend/src/i18n/en.json` | Modifier — 8 nouvelles clés dans `gitCredentials` |
| `frontend/src/i18n/fr.json` | Modifier — 8 nouvelles clés dans `gitCredentials` |

---

### Task 1 : Nouvelles fonctions SSH dans `ssh_keys.py`

**Files:**
- Modify: `backend/src/portal/ssh_keys.py`
- Create: `backend/tests/test_ssh_keys.py`

- [ ] **Step 1 : Créer le fichier de test avec les cas qui doivent échouer**

```python
# backend/tests/test_ssh_keys.py
from __future__ import annotations

import os
from pathlib import Path

import pytest


def _setup(tmp_path: Path) -> None:
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    import portal.settings as mod
    mod._settings = None


def test_generate_git_credential_ssh_key_creates_files(tmp_path: Path) -> None:
    _setup(tmp_path)
    from portal.ssh_keys import generate_git_credential_ssh_key

    key_path, public_key = generate_git_credential_ssh_key("alice", "my-key")

    priv = Path(key_path)
    pub = priv.parent / "id_ed25519.pub"
    assert priv.exists()
    assert priv.stat().st_mode & 0o777 == 0o600
    assert pub.exists()
    assert pub.stat().st_mode & 0o777 == 0o644
    assert public_key.startswith("ssh-ed25519 ")
    assert "devpod-git:alice/my-key" in public_key


def test_generate_git_credential_ssh_key_returns_consistent_pub(tmp_path: Path) -> None:
    _setup(tmp_path)
    from portal.ssh_keys import generate_git_credential_ssh_key

    key_path, public_key = generate_git_credential_ssh_key("alice", "my-key")
    pub_file = (Path(key_path).parent / "id_ed25519.pub").read_text(encoding="utf-8").strip()
    assert pub_file == public_key.strip()


def test_derive_git_credential_public_key_reads_existing_pub(tmp_path: Path) -> None:
    _setup(tmp_path)
    from portal.ssh_keys import generate_git_credential_ssh_key, derive_git_credential_public_key

    key_path, original_pub = generate_git_credential_ssh_key("alice", "my-key")
    derived = derive_git_credential_public_key(key_path)
    assert derived.strip() == original_pub.strip()


def test_derive_git_credential_public_key_recreates_missing_pub(tmp_path: Path) -> None:
    _setup(tmp_path)
    from portal.ssh_keys import generate_git_credential_ssh_key, derive_git_credential_public_key

    key_path, _ = generate_git_credential_ssh_key("alice", "my-key")
    pub_path = Path(key_path).parent / "id_ed25519.pub"
    pub_path.unlink()

    derived = derive_git_credential_public_key(key_path)

    assert derived.startswith("ssh-ed25519 ")
    assert pub_path.exists()
    assert pub_path.stat().st_mode & 0o777 == 0o644
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

```bash
cd backend && uv run pytest tests/test_ssh_keys.py -v
```

Attendu : `ImportError` ou `AttributeError` — les fonctions `generate_git_credential_ssh_key` et `derive_git_credential_public_key` n'existent pas encore.

- [ ] **Step 3 : Modifier `ssh_keys.py` — ajouter l'import et les deux fonctions**

Remplacer la ligne d'import existante :
```python
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
```
par :
```python
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_ssh_private_key,
)
```

Ajouter après la fonction `ensure_workspace_ssh_key`, avant `_atomic_write` :

```python
def generate_git_credential_ssh_key(login: str, cred_name: str) -> tuple[str, str]:
    """Génère une paire Ed25519 pour un credential git. Retourne (key_path, public_key)."""
    key_dir = safe_user_path(login, "keys", "git", cred_name)
    key_dir.mkdir(parents=True, exist_ok=True)

    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption())
    public_bytes = private_key.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)
    public_str = public_bytes.decode("ascii") + f" devpod-git:{login}/{cred_name}"

    priv_path = key_dir / "id_ed25519"
    pub_path = key_dir / "id_ed25519.pub"

    _atomic_write(priv_path, private_pem, mode=0o600)
    _atomic_write(pub_path, public_str.encode("ascii"), mode=0o644)

    return str(priv_path), public_str


def derive_git_credential_public_key(key_path: str) -> str:
    """Dérive la clé publique depuis la clé privée OpenSSH. Écrit .pub à côté. Retourne le texte."""
    priv_path = Path(key_path)
    pub_path = priv_path.parent / "id_ed25519.pub"

    if pub_path.exists():
        return pub_path.read_text(encoding="utf-8").strip()

    key_data = priv_path.read_bytes()
    private_key = load_ssh_private_key(key_data, password=None)
    public_bytes = private_key.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)
    public_str = public_bytes.decode("ascii")

    _atomic_write(pub_path, public_str.encode("ascii"), mode=0o644)
    return public_str
```

- [ ] **Step 4 : Lancer les tests pour vérifier qu'ils passent**

```bash
cd backend && uv run pytest tests/test_ssh_keys.py -v
```

Attendu : 4 tests PASSED.

- [ ] **Step 5 : Lint + mypy**

```bash
cd backend && uv run ruff check src/portal/ssh_keys.py tests/test_ssh_keys.py && uv run mypy src/portal/ssh_keys.py
```

Attendu : aucune erreur.

- [ ] **Step 6 : Commit**

```bash
git add backend/src/portal/ssh_keys.py backend/tests/test_ssh_keys.py
git commit -m "feat: ajoute generate_git_credential_ssh_key et derive_git_credential_public_key"
```

---

### Task 2 : Backend `me.py` — generate_key + endpoint public-key + PATCH .pub

**Files:**
- Modify: `backend/src/portal/routes/me.py`
- Modify: `backend/tests/routes/test_me.py`

- [ ] **Step 1 : Ajouter les tests qui doivent échouer dans `test_me.py`**

Ajouter à la fin de `backend/tests/routes/test_me.py` :

```python
# ── SSH key management tests ────────────────────────────────────────────────

def _real_ssh_pem() -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
    key = Ed25519PrivateKey.generate()
    return key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()).decode("utf-8")


def test_post_git_credential_generate_key_creates_credential(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/git-credentials",
            json={"name": "my-key", "host": "github.com", "kind": "ssh", "generate_key": True},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["kind"] == "ssh"
    assert "public_key" in data
    assert data["public_key"].startswith("ssh-ed25519 ")
    from portal.config.store import load_user
    cfg = load_user("alice")
    cred = next(c for c in cfg.git_credentials if c.name == "my-key")
    assert cred.key_path != ""
    from pathlib import Path as P
    priv = P(cred.key_path)
    assert priv.exists()
    assert (priv.parent / "id_ed25519.pub").exists()


def test_post_git_credential_generate_key_with_token_kind_returns_422(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/me/git-credentials",
            json={"name": "my-key", "host": "github.com", "kind": "token", "generate_key": True},
        )
    assert resp.status_code == 422


def test_post_git_credential_ssh_upload_derives_pub_for_valid_key(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    pem = _real_ssh_pem()
    with TestClient(app) as client:
        resp = client.post(
            "/me/git-credentials",
            json={"name": "gl-ssh", "host": "gitlab.com", "kind": "ssh", "private_key": pem},
        )
    assert resp.status_code == 201
    from portal.config.store import load_user
    from pathlib import Path as P
    cfg = load_user("alice")
    cred = next(c for c in cfg.git_credentials if c.name == "gl-ssh")
    assert (P(cred.key_path).parent / "id_ed25519.pub").exists()


def test_get_git_credential_public_key_on_generated(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        client.post(
            "/me/git-credentials",
            json={"name": "my-key", "host": "github.com", "kind": "ssh", "generate_key": True},
        )
        resp = client.get("/me/git-credentials/my-key/public-key")
    assert resp.status_code == 200
    assert resp.json()["public_key"].startswith("ssh-ed25519 ")


def test_get_git_credential_public_key_derives_on_the_fly(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    pem = _real_ssh_pem()
    with TestClient(app) as client:
        client.post(
            "/me/git-credentials",
            json={"name": "my-key", "host": "github.com", "kind": "ssh", "private_key": pem},
        )
        from portal.config.store import load_user as _lu
        from pathlib import Path as P
        cfg = _lu("alice")
        cred = next(c for c in cfg.git_credentials if c.name == "my-key")
        pub = P(cred.key_path).parent / "id_ed25519.pub"
        if pub.exists():
            pub.unlink()
        resp = client.get("/me/git-credentials/my-key/public-key")
    assert resp.status_code == 200
    assert resp.json()["public_key"].startswith("ssh-ed25519 ")


def test_get_git_credential_public_key_on_token_returns_404(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        _add_token_cred(client, name="gh")
        resp = client.get("/me/git-credentials/gh/public-key")
    assert resp.status_code == 404


def test_get_git_credential_public_key_not_found_returns_404(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/me/git-credentials/nope/public-key")
    assert resp.status_code == 404


def test_patch_git_credential_updates_pub_on_new_key(tmp_path: Path) -> None:
    _provision_alice(tmp_path)
    app = _make_app(tmp_path)
    pem = _real_ssh_pem()
    with TestClient(app) as client:
        client.post(
            "/me/git-credentials",
            json={"name": "my-key", "host": "github.com", "kind": "ssh", "generate_key": True},
        )
        resp = client.patch("/me/git-credentials/my-key", json={"private_key": pem})
    assert resp.status_code == 200
    from portal.config.store import load_user
    from pathlib import Path as P
    cfg = load_user("alice")
    cred = next(c for c in cfg.git_credentials if c.name == "my-key")
    assert (P(cred.key_path).parent / "id_ed25519.pub").exists()
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

```bash
cd backend && uv run pytest tests/routes/test_me.py::test_post_git_credential_generate_key_creates_credential tests/routes/test_me.py::test_get_git_credential_public_key_on_generated tests/routes/test_me.py::test_get_git_credential_public_key_on_token_returns_404 tests/routes/test_me.py::test_get_git_credential_public_key_not_found_returns_404 tests/routes/test_me.py::test_post_git_credential_generate_key_with_token_kind_returns_422 -v
```

Attendu : `422` ou `404` sur les endpoints inexistants, `ValidationError` sur `generate_key` inconnu.

- [ ] **Step 3a : Ajouter l'import dans `me.py`**

Après les imports existants (ligne `from ..devpod.git import run_git_ls_remote`), ajouter :

```python
from ..ssh_keys import derive_git_credential_public_key, generate_git_credential_ssh_key
```

- [ ] **Step 3b : Modifier `_GitCredentialCreate` — ajouter `generate_key`**

Remplacer la classe `_GitCredentialCreate` par :

```python
class _GitCredentialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    host: str
    kind: Literal["ssh", "token"]
    username: str = ""
    token: str = ""
    private_key: str = ""
    generate_key: bool = False
```

- [ ] **Step 3c : Modifier le bloc SSH dans `add_git_credential`**

Remplacer le bloc `key_path = ""` … `elif body.kind == "token":` par :

```python
    key_path = ""
    public_key: str | None = None
    if body.kind == "ssh":
        if body.generate_key:
            key_path, public_key = generate_git_credential_ssh_key(user.login, body.name)
        else:
            if not body.private_key.strip():
                raise HTTPException(
                    status_code=422, detail="private_key is required for SSH credentials"
                )
            key_dir = safe_user_path(user.login, "keys", "git", body.name)
            key_dir.mkdir(parents=True, exist_ok=True)
            key_file = key_dir / "id_ed25519"
            key_file.write_text(body.private_key.strip() + "\n", encoding="utf-8")
            key_file.chmod(0o600)
            key_path = str(key_file)
            try:
                derive_git_credential_public_key(key_path)
            except Exception:
                pass
    elif body.kind == "token":
        if body.generate_key:
            raise HTTPException(
                status_code=422, detail="generate_key is only supported for SSH credentials"
            )
        if not body.token.strip():
            raise HTTPException(status_code=422, detail="token is required for PAT credentials")
```

- [ ] **Step 3d : Modifier le `return` de `add_git_credential`**

Remplacer la ligne `return {"name": body.name, "host": host, "kind": body.kind}` par :

```python
    result: dict[str, object] = {"name": body.name, "host": host, "kind": body.kind}
    if public_key is not None:
        result["public_key"] = public_key
    return result
```

- [ ] **Step 3e : Modifier le bloc "nouvelle clé SSH" dans `patch_git_credential`**

Dans le bloc `else:` du `if body.private_key is None or body.private_key == "__UNCHANGED__":`, après `key_file.chmod(0o600)` et `new_key_path = str(key_file)`, ajouter :

```python
            try:
                derive_git_credential_public_key(new_key_path)
            except Exception:
                pass
```

Le bloc complet doit ressembler à :
```python
        else:
            old_key_path = cred.key_path
            key_dir = safe_user_path(user.login, "keys", "git", effective_name)
            key_dir.mkdir(parents=True, exist_ok=True)
            key_file = key_dir / "id_ed25519"
            key_file.write_text(body.private_key.strip() + "\n", encoding="utf-8")
            key_file.chmod(0o600)
            new_key_path = str(key_file)
            try:
                derive_git_credential_public_key(new_key_path)
            except Exception:
                pass
            if old_key_path and old_key_path != new_key_path:
                key_to_delete = Path(old_key_path)
```

- [ ] **Step 3f : Ajouter le nouveau endpoint GET avant `delete_git_credential`**

Insérer juste avant `@router.delete("/git-credentials/{name}")` :

```python
@router.get("/git-credentials/{name}/public-key")
async def get_git_credential_public_key(
    name: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, object]:
    cfg = load_user(user.login)
    cred = next((c for c in cfg.git_credentials if c.name == name), None)
    if not cred:
        raise HTTPException(status_code=404, detail=f"Credential {name!r} not found")
    if cred.kind != "ssh":
        raise HTTPException(status_code=404, detail="Public key only available for SSH credentials")
    if not cred.key_path:
        raise HTTPException(status_code=404, detail="No key file for this credential")
    try:
        public_key = derive_git_credential_public_key(cred.key_path)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Could not read public key") from exc
    return {"public_key": public_key}
```

- [ ] **Step 4 : Lancer tous les tests pour vérifier qu'ils passent**

```bash
cd backend && uv run pytest tests/routes/test_me.py -v
```

Attendu : tous les tests (anciens + 8 nouveaux) PASSED.

- [ ] **Step 5 : Lint + mypy**

```bash
cd backend && uv run ruff check src/portal/routes/me.py && uv run mypy src/portal/routes/me.py
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/portal/routes/me.py backend/tests/routes/test_me.py
git commit -m "feat: ajoute generate_key, endpoint /public-key et dérivation .pub sur upload SSH"
```

---

### Task 3 : Frontend hooks `useGitCredentials.ts`

**Files:**
- Modify: `frontend/src/features/git-credentials/useGitCredentials.ts`

- [ ] **Step 1 : Réécrire le fichier**

```typescript
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson, apiFetch } from '@/shared/api/client'

export interface GitCredentialSummary {
  name: string
  host: string
  kind: 'ssh' | 'token'
  username: string
  public_key?: string
}

interface AddCredentialPayload {
  name: string
  host: string
  kind: 'ssh' | 'token'
  username?: string
  token?: string
  private_key?: string
  generate_key?: boolean
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

export function useGitCredentialPublicKey(name: string, enabled: boolean) {
  return useQuery<{ public_key: string }>({
    queryKey: ['git-credential-public-key', name],
    queryFn: () =>
      apiFetchJson<{ public_key: string }>(
        `/me/git-credentials/${encodeURIComponent(name)}/public-key`,
      ),
    enabled,
    retry: false,
  })
}
```

- [ ] **Step 2 : Vérifier la compilation TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -i "useGitCredentials\|GitCredentialSummary" | head -10
```

Attendu : aucune ligne d'erreur sur ces symboles.

- [ ] **Step 3 : Commit**

```bash
git add frontend/src/features/git-credentials/useGitCredentials.ts
git commit -m "feat: ajoute public_key, generate_key et useGitCredentialPublicKey dans useGitCredentials"
```

---

### Task 4 : Créer `GitCredentialPublicKeyDialog.tsx`

**Files:**
- Create: `frontend/src/features/git-credentials/GitCredentialPublicKeyDialog.tsx`

- [ ] **Step 1 : Créer le composant**

```tsx
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
import { Textarea } from '@/components/ui/textarea'

interface Props {
  open: boolean
  publicKey: string
  onClose: () => void
}

export default function GitCredentialPublicKeyDialog({ open, publicKey, onClose }: Props) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  function handleCopy() {
    void navigator.clipboard.writeText(publicKey)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <Dialog open={open} onOpenChange={open => { if (!open) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('gitCredentials.publicKeyDialogTitle')}</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">{t('gitCredentials.publicKeyHint')}</p>
        <Textarea
          readOnly
          value={publicKey}
          className="font-mono text-xs"
          rows={4}
        />
        <div className="flex justify-end">
          <Button type="button" size="sm" onClick={handleCopy}>
            {copied ? (
              <>
                <Check className="mr-1.5 h-4 w-4" />
                {t('gitCredentials.publicKeyCopied')}
              </>
            ) : (
              <>
                <Copy className="mr-1.5 h-4 w-4" />
                {t('gitCredentials.publicKeyCopy')}
              </>
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 2 : Vérifier la compilation TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -i "GitCredentialPublicKeyDialog" | head -5
```

Attendu : aucune ligne d'erreur sur ce fichier.

- [ ] **Step 3 : Commit**

```bash
git add frontend/src/features/git-credentials/GitCredentialPublicKeyDialog.tsx
git commit -m "feat: ajoute GitCredentialPublicKeyDialog"
```

---

### Task 5 : Modifier `GitCredentialManager.tsx`

**Files:**
- Modify: `frontend/src/features/git-credentials/GitCredentialManager.tsx`

- [ ] **Step 1 : Ajouter `useEffect` à l'import React et les nouveaux imports**

Remplacer la ligne :
```typescript
import { useState, type FormEvent } from 'react'
```
par :
```typescript
import { useState, useEffect, type FormEvent } from 'react'
```

Remplacer le bloc d'import de `useGitCredentials` :
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
par :
```typescript
import {
  useGitCredentials,
  useAddGitCredential,
  useDeleteGitCredential,
  useUpdateGitCredential,
  useGitCredentialPublicKey,
  type GitCredentialSummary,
  type UpdateCredentialPayload,
} from './useGitCredentials'
import GitCredentialPublicKeyDialog from './GitCredentialPublicKeyDialog'
```

- [ ] **Step 2 : Ajouter les états pour la clé publique**

Après `const [editError, setEditError] = useState('')` :

```typescript
  const [publicKeyDialog, setPublicKeyDialog] = useState<{ name: string; key: string } | null>(null)
  const [publicKeyFetchName, setPublicKeyFetchName] = useState<string | null>(null)
```

- [ ] **Step 3 : Ajouter le hook lazy et les effets de bord**

Après les déclarations d'état, avant `const credentialList` :

```typescript
  const publicKeyQuery = useGitCredentialPublicKey(publicKeyFetchName ?? '', !!publicKeyFetchName)

  useEffect(() => {
    if (publicKeyQuery.isSuccess && publicKeyFetchName && publicKeyQuery.data) {
      setPublicKeyDialog({ name: publicKeyFetchName, key: publicKeyQuery.data.public_key })
      setPublicKeyFetchName(null)
    }
  }, [publicKeyQuery.isSuccess, publicKeyQuery.data, publicKeyFetchName])

  useEffect(() => {
    if (publicKeyQuery.isError && publicKeyFetchName) {
      setPublicKeyFetchName(null)
    }
  }, [publicKeyQuery.isError, publicKeyFetchName])
```

- [ ] **Step 4 : Ajouter `handleGenerate`**

Après `function handleDelete()` :

```typescript
  function handleGenerate() {
    setFormError('')
    addMutation.mutate(
      { name: form.name.trim(), host: effectiveHost, kind: 'ssh', generate_key: true, private_key: '' },
      {
        onSuccess: data => {
          if (data.public_key) {
            setPublicKeyDialog({ name: data.name, key: data.public_key })
          }
          resetForm()
        },
        onError: (err: unknown) =>
          setFormError(err instanceof Error ? err.message : t('gitCredentials.errors.add')),
      },
    )
  }
```

- [ ] **Step 5 : Modifier le bloc SSH du formulaire d'ajout**

Remplacer le bloc `{/* Champs SSH */}` dans le formulaire d'ajout :

```tsx
          {/* Champs SSH */}
          {form.kind === 'ssh' && (
            <div>
              <Label htmlFor="cred-key" className="text-xs">
                {t('gitCredentials.privateKey')}
              </Label>
              <Textarea
                id="cred-key"
                value={form.privateKey}
                onChange={e => setForm(f => ({ ...f, privateKey: e.target.value }))}
                placeholder={t('gitCredentials.privateKeyPlaceholder')}
                className="mt-1 font-mono text-xs"
                rows={6}
              />
              <div className="mt-1.5">
                <input
                  type="file"
                  accept=".pem,.key"
                  id="cred-key-file"
                  className="hidden"
                  onChange={e => {
                    const file = e.target.files?.[0]
                    if (!file) return
                    const reader = new FileReader()
                    reader.onload = ev =>
                      setForm(f => ({ ...f, privateKey: (ev.target?.result as string) ?? '' }))
                    reader.readAsText(file)
                    e.target.value = ''
                  }}
                />
                <Button type="button" variant="outline" size="sm" asChild>
                  <label htmlFor="cred-key-file" className="cursor-pointer">
                    {t('gitCredentials.loadKeyFile')}
                  </label>
                </Button>
              </div>
            </div>
          )}
```

- [ ] **Step 6 : Modifier les boutons du formulaire d'ajout**

Remplacer le bloc `<div className="flex gap-2 justify-end">` … `</div>` du formulaire d'ajout :

```tsx
          <div className="flex gap-2 justify-end">
            <Button type="button" variant="ghost" size="sm" onClick={resetForm}>
              {t('gitCredentials.cancel')}
            </Button>
            {form.kind === 'ssh' && (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                disabled={!form.name.trim() || !effectiveHost || addMutation.isPending}
                onClick={handleGenerate}
              >
                {addMutation.isPending ? '…' : t('gitCredentials.generateKey')}
              </Button>
            )}
            <Button type="submit" size="sm" disabled={addMutation.isPending}>
              {addMutation.isPending ? '…' : t('gitCredentials.save')}
            </Button>
          </div>
```

- [ ] **Step 7 : Ajouter le bouton clé publique dans la liste**

Remplacer le bloc `<div className="flex items-center gap-1">` … `</div>` de la liste :

```tsx
            <div className="flex items-center gap-1">
              {c.kind === 'ssh' && (
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8"
                  onClick={() => setPublicKeyFetchName(c.name)}
                  aria-label={t('gitCredentials.viewPublicKey')}
                  disabled={publicKeyFetchName === c.name}
                >
                  <KeyRound className="h-4 w-4" />
                </Button>
              )}
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
            </div>
```

- [ ] **Step 8 : Modifier le bloc SSH du formulaire d'édition**

Remplacer le bloc `{/* Champ SSH */}` dans le dialog d'édition :

```tsx
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
                      setEditForm(f =>
                        f
                          ? { ...f, privateKey: e.target.value, keyTouched: e.target.value !== '' }
                          : f,
                      )
                    }
                    placeholder={t('gitCredentials.privateKeyPlaceholder')}
                    className="mt-1 font-mono text-xs"
                    rows={6}
                  />
                  <div className="mt-1.5">
                    <input
                      type="file"
                      accept=".pem,.key"
                      id="edit-cred-key-file"
                      className="hidden"
                      onChange={e => {
                        const file = e.target.files?.[0]
                        if (!file) return
                        const reader = new FileReader()
                        reader.onload = ev =>
                          setEditForm(f =>
                            f
                              ? {
                                  ...f,
                                  privateKey: (ev.target?.result as string) ?? '',
                                  keyTouched: true,
                                }
                              : f,
                          )
                        reader.readAsText(file)
                        e.target.value = ''
                      }}
                    />
                    <Button type="button" variant="outline" size="sm" asChild>
                      <label htmlFor="edit-cred-key-file" className="cursor-pointer">
                        {t('gitCredentials.loadKeyFile')}
                      </label>
                    </Button>
                  </div>
                  {!editForm.keyTouched && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {t('gitCredentials.sshKeyUnchangedHint')}
                    </p>
                  )}
                </div>
              )}
```

- [ ] **Step 9 : Ajouter le `GitCredentialPublicKeyDialog` avant la fermeture du composant**

Juste avant `</div>` final (le `max-w-2xl`) :

```tsx
      {/* ── Dialog clé publique ──────────────────────────────────────── */}
      <GitCredentialPublicKeyDialog
        open={!!publicKeyDialog}
        publicKey={publicKeyDialog?.key ?? ''}
        onClose={() => setPublicKeyDialog(null)}
      />
```

- [ ] **Step 10 : Vérifier la compilation TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "GitCredentialManager\|useGitCredentials\|PublicKey" | head -10
```

Attendu : aucune erreur sur ces fichiers.

- [ ] **Step 11 : Commit**

```bash
git add frontend/src/features/git-credentials/GitCredentialManager.tsx
git commit -m "feat: ajout upload clé, génération Ed25519 et affichage clé publique dans GitCredentialManager"
```

---

### Task 6 : i18n — nouvelles clés FR + EN

**Files:**
- Modify: `frontend/src/i18n/en.json`
- Modify: `frontend/src/i18n/fr.json`

- [ ] **Step 1 : Ajouter les clés EN dans `gitCredentials`**

Dans `frontend/src/i18n/en.json`, dans l'objet `gitCredentials`, ajouter avant `"hosts"` :

```json
    "loadKeyFile": "Load from file",
    "generateKey": "Generate key",
    "viewPublicKey": "View public key",
    "publicKeyDialogTitle": "SSH Public Key",
    "publicKeyHint": "Paste this key into GitHub → Settings → SSH keys or GitLab → Repository → Settings → Deploy Keys.",
    "publicKeyCopy": "Copy",
    "publicKeyCopied": "Copied!",
```

Et dans l'objet `errors` existant de `gitCredentials`, ajouter après `"update"` :

```json
      "publicKey": "Could not retrieve public key."
```

- [ ] **Step 2 : Ajouter les clés FR dans `gitCredentials`**

Dans `frontend/src/i18n/fr.json`, dans l'objet `gitCredentials`, ajouter avant `"hosts"` :

```json
    "loadKeyFile": "Charger depuis un fichier",
    "generateKey": "Générer une clé",
    "viewPublicKey": "Voir la clé publique",
    "publicKeyDialogTitle": "Clé publique SSH",
    "publicKeyHint": "Copiez cette clé dans GitHub → Settings → SSH keys ou GitLab → Dépôt → Paramètres → Clés de déploiement.",
    "publicKeyCopy": "Copier",
    "publicKeyCopied": "Copié !",
```

Et dans l'objet `errors` existant de `gitCredentials`, ajouter après `"update"` :

```json
      "publicKey": "Impossible de récupérer la clé publique."
```

- [ ] **Step 3 : Vérifier la compilation TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -5
```

- [ ] **Step 4 : Commit**

```bash
git add frontend/src/i18n/en.json frontend/src/i18n/fr.json
git commit -m "feat: ajoute clés i18n pour gestion clés SSH des credentials git"
```

---

### Task 7 : Vérification finale

**Files:** Aucun fichier créé, uniquement vérifications.

- [ ] **Step 1 : Lancer la suite complète des tests backend**

```bash
cd backend && uv run pytest tests/ -v
```

Attendu : tous les tests PASSED (anciens + 4 dans `test_ssh_keys.py` + 8 dans `test_me.py`).

- [ ] **Step 2 : Lint + mypy complet backend**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
```

Attendu : aucune erreur.

- [ ] **Step 3 : Vérification build frontend**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -v "^D:\\srcs\\devpod-ui\\frontend\\src\\features\\admin" | head -20
```

Les 26 erreurs pré-existantes dans `src/features/admin/` sont antérieures à cette feature (confirmé par `git stash` en session précédente). Vérifier qu'aucune nouvelle erreur n'est introduite dans `src/features/git-credentials/`.

- [ ] **Step 4 : Vérifier git log**

```bash
git log --oneline -8
```

Attendu : les 6 commits de cette feature apparaissent proprement.
