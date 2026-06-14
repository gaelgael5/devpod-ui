# SSH Terminal flottant sur les hosts SSH — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter un bouton SSH dans la table des hosts admin (visible uniquement sur les lignes `type: "ssh"`) qui ouvre une fenêtre flottante draggable avec un vrai terminal xterm.js connecté au nœud via WebSocket proxy FastAPI.

**Architecture:** Le backend FastAPI ouvre un subprocess `ssh -i key_path user@host` et proxie stdin/stdout sur un WebSocket `WS /admin/hosts/{name}/ssh`. L'auth s'appuie sur le cookie de session Starlette existant. Le frontend `SshTerminalWindow.tsx` utilise xterm.js dans un portail React, drag géré par listeners natifs sans dépendance externe.

**Tech Stack:** Python 3.12 + FastAPI WebSocket + asyncio subprocess ; React 18 + TypeScript + @xterm/xterm + @xterm/addon-fit + React portal ; Vitest + MSW pour les tests frontend ; pytest + TestClient websocket pour le backend.

---

## Fichiers concernés

**Backend — nouveaux :**
- `backend/src/portal/routes/ssh_proxy.py`
- `backend/tests/test_ssh_proxy.py`

**Backend — modifiés :**
- `backend/src/portal/app.py` (1 import + 1 `include_router`)

**Frontend — nouveaux :**
- `frontend/src/features/admin/SshTerminalWindow.tsx`
- `frontend/src/features/admin/SshTerminalWindow.test.tsx`

**Frontend — modifiés :**
- `frontend/src/features/admin/AdminHosts.tsx` (état sshTarget + bouton SSH)
- `frontend/src/features/admin/AdminHosts.test.tsx` (2 nouveaux tests)
- `frontend/src/test/handlers.ts` (ajout host ssh dans mock)
- `frontend/src/i18n/fr.json` (clés sshTerminal)
- `frontend/src/i18n/en.json` (clés sshTerminal)

---

## Task 1 — Backend : validation et auth (ssh_proxy.py)

**Files:**
- Create: `backend/src/portal/routes/ssh_proxy.py`
- Create: `backend/tests/test_ssh_proxy.py`

- [ ] **Étape 1.1 — Écrire les tests de rejet**

```python
# backend/tests/test_ssh_proxy.py
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from starlette.requests import Request


# ── Fixtures ──────────────────────────────────────────────────────────────────

SSH_HOST_CONFIG = textwrap.dedent("""\
    version: "1"
    server:
      listen: "0.0.0.0:8080"
      base_domain: "dev.yoops.org"
      external_url: "https://dev.yoops.org"
      dev_mode: false
      log:
        level: "info"
        format: "text"
        output: ""
    auth:
      oidc:
        issuer: "https://security.yoops.org/realms/yoops"
        client_id: "workspace-portal"
        client_secret: "secret"
        scopes: ["openid", "profile", "email", "roles"]
        role_claim: "realm_access.roles"
        admin_role: "admin"
        user_role: "dev"
        username_claim: "preferred_username"
    secrets:
      backend: "inline"
    devpod:
      binary: "/usr/local/bin/devpod"
      defaults:
        ide: "openvscode"
        idle_timeout: "2h"
        dotfiles: ""
      client_cert_path: "/data/certs/portal"
    caddy:
      admin_api: "http://caddy:2019"
    cloudflare_manager:
      url: ""
      api_key: ""
    hosts:
      - name: "ssh-dev"
        type: "ssh"
        address: "debian@192.168.10.175"
        key_path: "{key_path}"
      - name: "docker-local"
        type: "docker-tls"
        docker_host: "tcp://192.168.1.50:2376"
    """)


@pytest.fixture
def data_root_with_ssh(tmp_data_root: Path, monkeypatch) -> Path:
    """Répertoire temporaire avec config SSH et clé factice."""
    key_dir = tmp_data_root / "keys" / "hosts"
    key_dir.mkdir(parents=True)
    key_file = key_dir / "ssh_dev_ed25519"
    key_file.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----\n")
    key_file.chmod(0o600)

    config = SSH_HOST_CONFIG.format(key_path=str(key_file))
    (tmp_data_root / "config.yaml").write_text(config)
    return tmp_data_root


def _make_client(data_root_with_ssh: Path, as_admin: bool = True) -> TestClient:
    """Crée un TestClient avec session admin (ou non)."""
    from portal.app import create_app

    app = create_app()

    # Endpoint de test uniquement : injecte la session sans passer par OIDC
    test_router = APIRouter()

    @test_router.get("/_test/login")
    async def _test_login(request: Request):
        if as_admin:
            request.session["user"] = {"login": "admin", "roles": ["admin"]}
        return {"ok": True}

    app.include_router(test_router)
    client = TestClient(app)
    client.get("/_test/login")
    return client


# ── Tests d'authentification ──────────────────────────────────────────────────

def test_ws_rejects_unauthenticated(data_root_with_ssh):
    from portal.app import create_app
    app = create_app()
    client = TestClient(app)  # pas de login → pas de session

    with pytest.raises(Exception) as exc_info:
        with client.websocket_connect("/admin/hosts/ssh-dev/ssh"):
            pass
    assert exc_info.value.code == 4001


def test_ws_rejects_non_admin(data_root_with_ssh):
    from portal.app import create_app
    app = create_app()
    test_router = APIRouter()

    @test_router.get("/_test/login-user")
    async def _login_user(request: Request):
        request.session["user"] = {"login": "alice", "roles": ["dev"]}
        return {"ok": True}

    app.include_router(test_router)
    client = TestClient(app)
    client.get("/_test/login-user")

    with pytest.raises(Exception) as exc_info:
        with client.websocket_connect("/admin/hosts/ssh-dev/ssh"):
            pass
    assert exc_info.value.code == 4001


# ── Tests de validation de la config ─────────────────────────────────────────

def test_ws_rejects_unknown_host(data_root_with_ssh):
    client = _make_client(data_root_with_ssh)
    with pytest.raises(Exception) as exc_info:
        with client.websocket_connect("/admin/hosts/inexistant/ssh"):
            pass
    assert exc_info.value.code == 4004


def test_ws_rejects_docker_tls_host(data_root_with_ssh):
    client = _make_client(data_root_with_ssh)
    with pytest.raises(Exception) as exc_info:
        with client.websocket_connect("/admin/hosts/docker-local/ssh"):
            pass
    assert exc_info.value.code == 4022


def test_ws_rejects_empty_key_path(tmp_data_root, monkeypatch):
    config = SSH_HOST_CONFIG.format(key_path="")
    (tmp_data_root / "config.yaml").write_text(config)
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_data_root))

    from portal.app import create_app
    app = create_app()
    test_router = APIRouter()

    @test_router.get("/_test/login")
    async def _login(request: Request):
        request.session["user"] = {"login": "admin", "roles": ["admin"]}
        return {"ok": True}

    app.include_router(test_router)
    client = TestClient(app)
    client.get("/_test/login")

    with pytest.raises(Exception) as exc_info:
        with client.websocket_connect("/admin/hosts/ssh-dev/ssh"):
            pass
    assert exc_info.value.code == 4022


def test_ws_rejects_key_path_outside_data_root(tmp_data_root, monkeypatch, tmp_path):
    outside_key = tmp_path / "evil_key"
    outside_key.write_text("fake")
    config = SSH_HOST_CONFIG.format(key_path=str(outside_key))
    (tmp_data_root / "config.yaml").write_text(config)
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_data_root))

    from portal.app import create_app
    app = create_app()
    test_router = APIRouter()

    @test_router.get("/_test/login")
    async def _login(request: Request):
        request.session["user"] = {"login": "admin", "roles": ["admin"]}
        return {"ok": True}

    app.include_router(test_router)
    client = TestClient(app)
    client.get("/_test/login")

    with pytest.raises(Exception) as exc_info:
        with client.websocket_connect("/admin/hosts/ssh-dev/ssh"):
            pass
    assert exc_info.value.code == 4022


def test_ws_rejects_missing_key_file(tmp_data_root, monkeypatch):
    config = SSH_HOST_CONFIG.format(key_path=str(tmp_data_root / "keys" / "absent"))
    (tmp_data_root / "config.yaml").write_text(config)
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_data_root))

    from portal.app import create_app
    app = create_app()
    test_router = APIRouter()

    @test_router.get("/_test/login")
    async def _login(request: Request):
        request.session["user"] = {"login": "admin", "roles": ["admin"]}
        return {"ok": True}

    app.include_router(test_router)
    client = TestClient(app)
    client.get("/_test/login")

    with pytest.raises(Exception) as exc_info:
        with client.websocket_connect("/admin/hosts/ssh-dev/ssh"):
            pass
    assert exc_info.value.code == 4022
```

- [ ] **Étape 1.2 — Lancer les tests pour vérifier qu'ils échouent**

```
cd backend && uv run pytest tests/test_ssh_proxy.py -v
```

Résultat attendu : `ImportError` ou `ModuleNotFoundError` sur `portal.routes.ssh_proxy`.

- [ ] **Étape 1.3 — Implémenter ssh_proxy.py (validation uniquement, pas encore le proxy)**

```python
# backend/src/portal/routes/ssh_proxy.py
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import structlog
from fastapi import APIRouter, WebSocket

from ..config.store import _data_root, load_global
from ..settings import get_settings

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["ssh-proxy"])


@router.websocket("/hosts/{name}/ssh")
async def host_ssh_terminal(name: str, websocket: WebSocket) -> None:
    await websocket.accept()

    # ── Auth ──────────────────────────────────────────────────────────────────
    user_data = websocket.session.get("user")
    settings = get_settings()
    if not user_data or not isinstance(user_data, dict):
        await websocket.close(code=4001, reason="Not authenticated")
        return
    if settings.oidc_admin_role not in user_data.get("roles", []):
        _log.warning("ws_ssh_admin_denied", login=user_data.get("login"))
        await websocket.close(code=4001, reason="Admin role required")
        return

    # ── Config ────────────────────────────────────────────────────────────────
    cfg = load_global()
    host = next((h for h in cfg.hosts if h.name == name), None)
    if host is None:
        await websocket.close(code=4004, reason=f"Host {name!r} not found")
        return
    if host.type != "ssh":
        await websocket.close(code=4022, reason=f"Host {name!r} is not of type ssh")
        return
    if not host.key_path:
        await websocket.close(code=4022, reason="key_path not configured for this host")
        return

    # ── Sécurité key_path ─────────────────────────────────────────────────────
    key_path = Path(host.key_path).resolve()
    data_root = _data_root().resolve()
    if not key_path.is_relative_to(data_root):
        _log.warning("ws_ssh_key_path_traversal", key_path=str(key_path))
        await websocket.close(code=4022, reason="key_path must be under data root")
        return
    if not key_path.exists():
        await websocket.close(code=4022, reason=f"key_path does not exist: {host.key_path}")
        return

    # ── Proxy SSH ─────────────────────────────────────────────────────────────
    address = host.address  # format "user@host"
    _log.info("ws_ssh_open", host=name, address=address, admin=user_data.get("login"))

    proc = await asyncio.create_subprocess_exec(
        "ssh",
        "-i", str(key_path),
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=no",
        address,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    async def _ws_to_ssh() -> None:
        try:
            while True:
                data = await websocket.receive_bytes()
                if proc.stdin and not proc.stdin.is_closing():
                    proc.stdin.write(data)
                    await proc.stdin.drain()
        except Exception:
            pass

    async def _ssh_to_ws() -> None:
        try:
            assert proc.stdout is not None
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                await websocket.send_bytes(chunk)
        except Exception:
            pass

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

    _log.info("ws_ssh_closed", host=name, returncode=proc.returncode)
```

- [ ] **Étape 1.4 — Lancer les tests de validation**

```
cd backend && uv run pytest tests/test_ssh_proxy.py -v -k "not proxy"
```

Résultat attendu : tous les tests de validation PASSENT.

- [ ] **Étape 1.5 — Commit**

```
git add backend/src/portal/routes/ssh_proxy.py backend/tests/test_ssh_proxy.py
git commit -m "feat(ssh-proxy): WebSocket SSH proxy — validation auth + config"
```

---

## Task 2 — Backend : test du proxy nominal et fermeture

**Files:**
- Modify: `backend/tests/test_ssh_proxy.py` (ajout de 2 tests)

- [ ] **Étape 2.1 — Ajouter les tests proxy nominal et fermeture WebSocket**

Ajouter en fin de `backend/tests/test_ssh_proxy.py` :

```python
# ── Tests du proxy nominal ────────────────────────────────────────────────────

def test_ws_proxy_echoes_data(data_root_with_ssh, tmp_path):
    """Le subprocess SSH factice fait echo — on vérifie que les bytes arrivent au WS."""
    import sys

    # Écrase la clé pour qu'elle pointe vers le bon data_root
    from portal.config.store import _data_root
    key_file = _data_root() / "keys" / "hosts" / "ssh_dev_ed25519"

    # Remplacer "ssh" par un script echo dans le PATH du test
    echo_script = tmp_path / "ssh"
    echo_script.write_text(
        "#!/bin/sh\ncat\n"  # recopie stdin sur stdout — simule un terminal echo
    )
    echo_script.chmod(0o755)

    import os
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{tmp_path}:{old_path}"

    try:
        client = _make_client(data_root_with_ssh)
        with client.websocket_connect("/admin/hosts/ssh-dev/ssh") as ws:
            ws.send_bytes(b"hello")
            data = ws.receive_bytes()
            assert data == b"hello"
    finally:
        os.environ["PATH"] = old_path


def test_ws_close_kills_subprocess(data_root_with_ssh, tmp_path):
    """Fermer le WebSocket tue le subprocess SSH."""
    import os

    # Script SSH qui dort indéfiniment + écrit son PID dans un fichier
    pid_file = tmp_path / "ssh.pid"
    sleep_script = tmp_path / "ssh"
    sleep_script.write_text(
        f"#!/bin/sh\necho $$ > {pid_file}\nsleep 60\n"
    )
    sleep_script.chmod(0o755)

    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{tmp_path}:{old_path}"

    try:
        client = _make_client(data_root_with_ssh)
        with client.websocket_connect("/admin/hosts/ssh-dev/ssh"):
            # Attendre que le PID soit écrit
            import time
            for _ in range(20):
                if pid_file.exists():
                    break
                time.sleep(0.1)
            assert pid_file.exists(), "Le script SSH ne s'est pas lancé"
            pid = int(pid_file.read_text().strip())
        # WebSocket fermé — le subprocess doit être mort
        time.sleep(0.3)
        import signal
        try:
            os.kill(pid, 0)  # lève OSError si le process n'existe plus
            alive = True
        except OSError:
            alive = False
        assert not alive, f"Subprocess PID {pid} toujours vivant après fermeture WS"
    finally:
        os.environ["PATH"] = old_path
```

- [ ] **Étape 2.2 — Lancer tous les tests ssh_proxy**

```
cd backend && uv run pytest tests/test_ssh_proxy.py -v
```

Résultat attendu : tous les tests PASSENT (les tests proxy peuvent être lents ~1s).

- [ ] **Étape 2.3 — Commit**

```
git add backend/tests/test_ssh_proxy.py
git commit -m "test(ssh-proxy): proxy nominal echo + fermeture WebSocket tue subprocess"
```

---

## Task 3 — Backend : enregistrement dans app.py

**Files:**
- Modify: `backend/src/portal/app.py`

- [ ] **Étape 3.1 — Ajouter l'import et le `include_router`**

Dans `backend/src/portal/app.py`, ajouter après la ligne `from .routes.recipes import router_public as recipes_public_router` :

```python
from .routes.ssh_proxy import router as ssh_proxy_router
```

Et dans la fonction `create_app()`, après `app.include_router(recipes_admin_router, prefix="/admin")` :

```python
app.include_router(ssh_proxy_router, prefix="/admin")
```

- [ ] **Étape 3.2 — Vérifier que tous les tests backend passent**

```
cd backend && uv run pytest -v
```

Résultat attendu : tous les tests PASSENT.

- [ ] **Étape 3.3 — Lint et mypy**

```
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
```

Résultat attendu : aucune erreur.

- [ ] **Étape 3.4 — Commit**

```
git add backend/src/portal/app.py
git commit -m "feat(ssh-proxy): enregistrement du router ssh_proxy dans app"
```

---

## Task 4 — Frontend : i18n + handler MSW

**Files:**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`
- Modify: `frontend/src/test/handlers.ts`

- [ ] **Étape 4.1 — Ajouter les clés i18n SSH dans fr.json**

Dans `frontend/src/i18n/fr.json`, dans l'objet `"admin"`, ajouter après `"deleteHostDescription"` :

```json
"sshTerminal": {
  "openBtn": "SSH",
  "windowTitle": "Terminal SSH",
  "closeLabel": "Fermer le terminal",
  "connClosed": "\r\n[Connexion fermée]\r\n",
  "connError": "\r\n[Erreur de connexion]\r\n"
}
```

- [ ] **Étape 4.2 — Ajouter les clés i18n SSH dans en.json**

Dans `frontend/src/i18n/en.json`, dans l'objet `"admin"`, ajouter après `"deleteHostDescription"` :

```json
"sshTerminal": {
  "openBtn": "SSH",
  "windowTitle": "SSH Terminal",
  "closeLabel": "Close terminal",
  "connClosed": "\r\n[Connection closed]\r\n",
  "connError": "\r\n[Connection error]\r\n"
}
```

- [ ] **Étape 4.3 — Ajouter un host SSH dans handlers.ts**

Dans `frontend/src/test/handlers.ts`, remplacer le handler `GET /admin/hosts` :

```typescript
http.get('/admin/hosts', () =>
  HttpResponse.json([
    { name: 'pve1', type: 'docker-tls', default: true, docker_host: 'tcp://192.168.1.50:2376' },
    { name: 'pve2', type: 'docker-tls', default: false, docker_host: 'tcp://192.168.1.51:2376' },
    { name: 'ssh-dev', type: 'ssh', default: false, address: 'debian@192.168.10.175', key_path: '/data/keys/hosts/ssh_dev_ed25519' },
  ])
),
```

- [ ] **Étape 4.4 — Vérifier que les tests existants passent toujours**

```
cd frontend && npm test
```

Résultat attendu : tous les tests PASSENT.

- [ ] **Étape 4.5 — Commit**

```
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json frontend/src/test/handlers.ts
git commit -m "feat(ssh-terminal): i18n clés SSH + host ssh dans mock MSW"
```

---

## Task 5 — Frontend : SshTerminalWindow (TDD)

**Files:**
- Modify: `frontend/package.json` (via npm install)
- Create: `frontend/src/features/admin/SshTerminalWindow.tsx`
- Create: `frontend/src/features/admin/SshTerminalWindow.test.tsx`

- [ ] **Étape 5.1 — Installer xterm**

```
cd frontend && npm install @xterm/xterm @xterm/addon-fit
```

Vérifier dans `package.json` que `@xterm/xterm` et `@xterm/addon-fit` apparaissent dans `dependencies`.

- [ ] **Étape 5.2 — Écrire les tests SshTerminalWindow**

```typescript
// frontend/src/features/admin/SshTerminalWindow.test.tsx
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { I18nextProvider } from 'react-i18next'
import i18n from '@/i18n'
import SshTerminalWindow from './SshTerminalWindow'
import type { HostConfig } from './useHosts'

// ── Mocks xterm ───────────────────────────────────────────────────────────────
const mockTerminalInstance = {
  open: vi.fn(),
  dispose: vi.fn(),
  onData: vi.fn().mockReturnValue({ dispose: vi.fn() }),
  write: vi.fn(),
  loadAddon: vi.fn(),
  focus: vi.fn(),
}
vi.mock('@xterm/xterm', () => ({
  Terminal: vi.fn(() => mockTerminalInstance),
}))
vi.mock('@xterm/addon-fit', () => ({
  FitAddon: vi.fn(() => ({ fit: vi.fn(), dispose: vi.fn() })),
}))

// ── Mock WebSocket ────────────────────────────────────────────────────────────
class MockWebSocket {
  static lastInstance: MockWebSocket
  url: string
  binaryType = 'arraybuffer'
  readyState = WebSocket.CONNECTING
  onopen: (() => void) | null = null
  onmessage: ((e: MessageEvent) => void) | null = null
  onclose: ((e: CloseEvent) => void) | null = null
  onerror: ((e: Event) => void) | null = null
  send = vi.fn()
  close = vi.fn()
  constructor(url: string) {
    this.url = url
    MockWebSocket.lastInstance = this
  }
}
vi.stubGlobal('WebSocket', MockWebSocket)

// ── Helpers ───────────────────────────────────────────────────────────────────
const SSH_HOST: HostConfig = {
  name: 'ssh-dev',
  type: 'ssh',
  address: 'debian@192.168.10.175',
  key_path: '/data/keys/hosts/ssh_dev_ed25519',
}

function renderWindow(onClose = vi.fn()) {
  return render(
    <I18nextProvider i18n={i18n}>
      <SshTerminalWindow host={SSH_HOST} onClose={onClose} />
    </I18nextProvider>
  )
}

// ── Tests ─────────────────────────────────────────────────────────────────────
describe('SshTerminalWindow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('affiche l'adresse SSH dans le header', () => {
    renderWindow()
    expect(screen.getByText(/debian@192\.168\.10\.175/)).toBeInTheDocument()
  })

  it('se connecte au bon endpoint WebSocket', () => {
    renderWindow()
    expect(MockWebSocket.lastInstance.url).toContain('/admin/hosts/ssh-dev/ssh')
  })

  it('appelle onClose et ferme le WebSocket au clic sur le bouton rouge', async () => {
    const onClose = vi.fn()
    renderWindow(onClose)
    const btn = screen.getByRole('button', { name: /fermer|close/i })
    await userEvent.click(btn)
    expect(onClose).toHaveBeenCalledOnce()
    expect(MockWebSocket.lastInstance.close).toHaveBeenCalled()
  })

  it('écrit dans le terminal à la réception d'un message WebSocket', () => {
    renderWindow()
    act(() => {
      MockWebSocket.lastInstance.onmessage?.({
        data: new ArrayBuffer(5),
      } as MessageEvent)
    })
    expect(mockTerminalInstance.write).toHaveBeenCalled()
  })

  it('dispose le terminal au démontage', () => {
    const { unmount } = renderWindow()
    unmount()
    expect(mockTerminalInstance.dispose).toHaveBeenCalled()
    expect(MockWebSocket.lastInstance.close).toHaveBeenCalled()
  })
})
```

- [ ] **Étape 5.3 — Lancer les tests pour vérifier qu'ils échouent**

```
cd frontend && npm test -- SshTerminalWindow
```

Résultat attendu : FAIL — `Cannot find module './SshTerminalWindow'`.

- [ ] **Étape 5.4 — Implémenter SshTerminalWindow.tsx**

```typescript
// frontend/src/features/admin/SshTerminalWindow.tsx
import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import type { HostConfig } from './useHosts'

interface Props {
  host: HostConfig
  onClose: () => void
}

export default function SshTerminalWindow({ host, onClose }: Props) {
  const { t } = useTranslation()
  const termRef = useRef<HTMLDivElement>(null)
  const posRef = useRef({ x: Math.max(0, window.innerWidth - 640), y: 80 })
  const winRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)
  const dragOrigin = useRef({ mx: 0, my: 0, wx: 0, wy: 0 })
  const wsRef = useRef<WebSocket | null>(null)

  // ── Terminal + WebSocket ───────────────────────────────────────────────────
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

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(
      `${proto}//${window.location.host}/admin/hosts/${encodeURIComponent(host.name)}/ssh`
    )
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    const dataDisposable = terminal.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(data)
    })

    ws.onmessage = (e) => {
      const data = e.data instanceof ArrayBuffer ? new Uint8Array(e.data) : e.data
      terminal.write(data)
    }
    ws.onclose = () => terminal.write(t('admin.sshTerminal.connClosed'))
    ws.onerror = () => terminal.write(t('admin.sshTerminal.connError'))

    return () => {
      dataDisposable.dispose()
      ws.close()
      terminal.dispose()
      wsRef.current = null
    }
  }, [host.name, t])

  // ── Drag ──────────────────────────────────────────────────────────────────
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
    dragOrigin.current = {
      mx: e.clientX, my: e.clientY,
      wx: posRef.current.x, wy: posRef.current.y,
    }
    e.preventDefault()
  }

  function handleClose() {
    wsRef.current?.close()
    onClose()
  }

  const window_ = (
    <div
      ref={winRef}
      style={{
        position: 'fixed',
        left: posRef.current.x,
        top: posRef.current.y,
        width: 600,
        zIndex: 9999,
        borderRadius: 8,
        overflow: 'hidden',
        boxShadow: '0 8px 32px rgba(0,0,0,0.45)',
      }}
    >
      {/* Header */}
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
        }}
      >
        <span style={{ fontSize: 12, color: '#a0a0c0', fontFamily: 'monospace' }}>
          ⚡ {host.address}
        </span>
        <button
          onClick={handleClose}
          aria-label={t('admin.sshTerminal.closeLabel')}
          style={{
            width: 13,
            height: 13,
            borderRadius: '50%',
            background: '#ef4444',
            border: 'none',
            cursor: 'pointer',
            display: 'block',
          }}
        />
      </div>

      {/* Terminal */}
      <div
        ref={termRef}
        style={{ background: '#0d0d1a', height: 360, padding: '4px 2px' }}
      />
    </div>
  )

  return createPortal(window_, document.body)
}
```

- [ ] **Étape 5.5 — Lancer les tests SshTerminalWindow**

```
cd frontend && npm test -- SshTerminalWindow
```

Résultat attendu : 5/5 tests PASSENT.

- [ ] **Étape 5.6 — Vérifier le build TypeScript**

```
cd frontend && npx tsc --noEmit
```

Résultat attendu : aucune erreur.

- [ ] **Étape 5.7 — Commit**

```
git add frontend/package.json frontend/package-lock.json frontend/src/features/admin/SshTerminalWindow.tsx frontend/src/features/admin/SshTerminalWindow.test.tsx
git commit -m "feat(ssh-terminal): SshTerminalWindow — xterm.js + drag + WebSocket proxy"
```

---

## Task 6 — Frontend : bouton SSH dans AdminHosts

**Files:**
- Modify: `frontend/src/features/admin/AdminHosts.tsx`
- Modify: `frontend/src/features/admin/AdminHosts.test.tsx`

- [ ] **Étape 6.1 — Écrire les nouveaux tests AdminHosts**

Ajouter dans le `describe('AdminHosts')` de `frontend/src/features/admin/AdminHosts.test.tsx` :

```typescript
it('n\'affiche pas le bouton SSH sur une ligne docker-tls', async () => {
  renderWithProviders(<AdminHosts />)
  await waitFor(() => expect(screen.getByText('pve1')).toBeInTheDocument())
  // pve1 est docker-tls — pas de bouton SSH sur sa ligne
  const rows = screen.getAllByRole('row')
  const pve1Row = rows.find(r => r.textContent?.includes('pve1'))
  expect(pve1Row).toBeDefined()
  expect(pve1Row!.querySelector('button[data-ssh]')).toBeNull()
})

it('affiche le bouton SSH sur une ligne ssh et ouvre la fenêtre au clic', async () => {
  renderWithProviders(<AdminHosts />)
  await waitFor(() => expect(screen.getByText('ssh-dev')).toBeInTheDocument())
  const sshBtn = screen.getByRole('button', { name: /^SSH$/i })
  expect(sshBtn).toBeInTheDocument()
  await userEvent.click(sshBtn)
  // SshTerminalWindow est rendu dans un portail — son header contient l'adresse
  expect(screen.getByText(/debian@192\.168\.10\.175/)).toBeInTheDocument()
})
```

Ajouter en tête du fichier si absent :

```typescript
import userEvent from '@testing-library/user-event'
```

Et ajouter le mock xterm + WebSocket (identique à SshTerminalWindow.test.tsx) en début de fichier :

```typescript
vi.mock('@xterm/xterm', () => ({
  Terminal: vi.fn(() => ({
    open: vi.fn(), dispose: vi.fn(),
    onData: vi.fn().mockReturnValue({ dispose: vi.fn() }),
    write: vi.fn(), loadAddon: vi.fn(), focus: vi.fn(),
  })),
}))
vi.mock('@xterm/addon-fit', () => ({
  FitAddon: vi.fn(() => ({ fit: vi.fn(), dispose: vi.fn() })),
}))
class MockWebSocket {
  binaryType = 'arraybuffer'; readyState = WebSocket.CONNECTING
  onopen = null; onmessage = null; onclose = null; onerror = null
  send = vi.fn(); close = vi.fn()
  constructor(public url: string) {}
}
vi.stubGlobal('WebSocket', MockWebSocket)
```

- [ ] **Étape 6.2 — Lancer les tests pour vérifier qu'ils échouent**

```
cd frontend && npm test -- AdminHosts
```

Résultat attendu : les 2 nouveaux tests ÉCHOUENT (bouton SSH absent dans le rendu actuel).

- [ ] **Étape 6.3 — Modifier AdminHosts.tsx**

Ajouter l'import en tête :

```typescript
import SshTerminalWindow from './SshTerminalWindow'
```

Ajouter l'état dans le composant `AdminHosts`, après les déclarations existantes :

```typescript
const [sshTarget, setSshTarget] = useState<HostConfig | null>(null)
```

Dans la cellule d'actions (la `<td>` avec `justify-end`), remplacer le contenu par :

```tsx
<div className="flex items-center justify-end gap-1">
  <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => openEdit(h)}
    aria-label={t('workspaces.actions.edit')}>
    <Pencil className="h-3.5 w-3.5" />
  </Button>
  <Button size="icon" variant="ghost" className="h-7 w-7 text-destructive hover:text-destructive"
    onClick={() => confirmDelete(h.name)} aria-label={t('admin.deleteHost')}>
    <Trash2 className="h-3.5 w-3.5" />
  </Button>
  {h.type === 'ssh' && (
    <>
      <span className="mx-0.5 h-4 w-px bg-border" aria-hidden />
      <Button
        size="sm"
        variant="outline"
        className="h-7 px-2 text-xs font-semibold text-green-700 border-green-600 hover:bg-green-50"
        data-ssh
        onClick={() => setSshTarget(h)}
        aria-label={t('admin.sshTerminal.openBtn')}
      >
        {t('admin.sshTerminal.openBtn')}
      </Button>
    </>
  )}
</div>
```

Ajouter en bas du JSX retourné, juste avant la dernière balise `</div>` fermante :

```tsx
{sshTarget && (
  <SshTerminalWindow host={sshTarget} onClose={() => setSshTarget(null)} />
)}
```

- [ ] **Étape 6.4 — Lancer tous les tests frontend**

```
cd frontend && npm test
```

Résultat attendu : tous les tests PASSENT.

- [ ] **Étape 6.5 — Vérifier le build TypeScript**

```
cd frontend && npx tsc --noEmit
```

Résultat attendu : aucune erreur.

- [ ] **Étape 6.6 — Commit**

```
git add frontend/src/features/admin/AdminHosts.tsx frontend/src/features/admin/AdminHosts.test.tsx
git commit -m "feat(ssh-terminal): bouton SSH dans AdminHosts + SshTerminalWindow"
```

---

## Vérification finale

- [ ] Suite complète backend

```
cd backend && uv run pytest -v && uv run ruff check src/ tests/ && uv run mypy src/
```

- [ ] Suite complète frontend

```
cd frontend && npm test && npx tsc --noEmit
```

- [ ] Build de production frontend (vérifie que le bundle passe)

```
cd frontend && npm run build
```
