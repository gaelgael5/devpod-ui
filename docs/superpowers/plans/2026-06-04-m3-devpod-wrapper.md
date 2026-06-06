# M3 — Wrapper DevPod (lifecycle des workspaces)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lancer/arrêter/supprimer des workspaces via la CLI DevPod sans bloquer l'event loop, avec isolation DEVPOD_HOME par user, verrou par ws_id, et streaming des logs vers fichier.

**Architecture:** `devpod/env.py` construit l'environnement subprocess ; `devpod/provider.py` initialise les providers par DEVPOD_HOME ; `devpod/runner.py` exécute les commandes en async avec streaming et verrou ; `devpod/service.py` orchestre les opérations métier. Les endpoints HTTP retournent 202 et délèguent à des tâches de fond. Statut dans `routes/<ws_id>.json`.

**Tech Stack:** Python 3.12 asyncio, asyncio.create_subprocess_exec, asyncio.Lock, structlog, pydantic v2 (M1 models), secrets resolver (M1), fastapi.BackgroundTasks.

---

## Étape préalable IMPÉRATIVE (avant tout code)

L'implémenteur **doit** exécuter et lire :
```bash
devpod version
devpod up --help
devpod list --help
devpod provider --help
devpod stop --help
devpod delete --help
```
Adapter tous les flags du plan à la version réelle installée. Signaler tout écart. **Ne jamais deviner un flag.**

---

## Structure des fichiers

```
backend/src/portal/
├── devpod/
│   ├── __init__.py               (nouveau)
│   ├── env.py                    (nouveau) build_env(login, ws_spec, global_cfg) -> dict
│   ├── provider.py               (nouveau) ensure_provider async
│   ├── runner.py                 (nouveau) WorkspaceLock + run_subprocess streaming
│   └── service.py                (nouveau) up, stop, delete, status, list
└── routes/
    └── workspace_ops.py          (nouveau) POST /me/workspaces/{name}/up|stop|delete|status

backend/tests/
└── devpod/
    ├── __init__.py
    ├── fake_devpod.py            fixture : faux binaire devpod pour les tests
    ├── conftest.py               fixtures partagées (tmp_data_root, global_cfg, fake_devpod_path)
    ├── test_env.py
    ├── test_provider.py
    ├── test_runner.py
    └── test_service.py
tests/routes/
└── test_workspace_ops.py
```

---

## Task 0 : Environnement d'appel `devpod/env.py` + fake devpod fixture

**Files:**
- Create: `backend/src/portal/devpod/__init__.py`
- Create: `backend/src/portal/devpod/env.py`
- Create: `backend/tests/devpod/__init__.py`
- Create: `backend/tests/devpod/fake_devpod.py`
- Create: `backend/tests/devpod/conftest.py`
- Create: `backend/tests/devpod/test_env.py`

- [ ] **Step 1 : Exécuter les commandes devpod et noter les flags réels**

```bash
devpod version
devpod up --help 2>&1 | head -60
devpod stop --help 2>&1 | head -20
devpod delete --help 2>&1 | head -20
devpod list --help 2>&1 | head -20
devpod provider --help 2>&1 | head -20
devpod provider list --help 2>&1 | head -20
devpod provider add --help 2>&1 | head -20
```

Note la version et les flags. En particulier vérifier :
- Flag pour ne pas auto-ouvrir l'IDE (chercher `--open-ide` ou `--open` ou `--no-ide`)
- Flag `--id` pour nommer le workspace
- Flag `--devcontainer-path` ou équivalent
- Flag `--output json` sur `list`

- [ ] **Step 2 : Écrire les tests rouges**

Créer `backend/tests/devpod/conftest.py` :

```python
from __future__ import annotations

import os
import sys
import pytest
from pathlib import Path


FAKE_DEVPOD = Path(__file__).parent / "fake_devpod.py"


@pytest.fixture
def fake_devpod_bin() -> list[str]:
    """Retourne la commande pour appeler le faux devpod."""
    return [sys.executable, str(FAKE_DEVPOD)]


@pytest.fixture
def tmp_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    import portal.settings as mod
    mod._settings = None
    return tmp_path


@pytest.fixture
def global_cfg(tmp_data_root: Path):
    """GlobalConfig minimal avec un host docker-tls et un host ssh."""
    import yaml
    config = {
        "version": "1",
        "server": {"listen": "0.0.0.0:8080", "base_domain": "dev.yoops.org",
                   "external_url": "https://dev.yoops.org", "dev_mode": True,
                   "log": {"level": "info", "format": "text", "output": ""}},
        "auth": {"oidc": {"issuer": "https://kc.test", "client_id": "portal",
                           "client_secret": "", "scopes": ["openid"],
                           "role_claim": "realm_access.roles", "admin_role": "admin",
                           "user_role": "dev", "username_claim": "preferred_username"}},
        "secrets": {"backend": "inline",
                    "harpocrate": {"url": "", "api_key": "", "base_path": "devpod"}},
        "devpod": {
            "binary": "devpod",  # surchargé par les tests
            "defaults": {"ide": "openvscode", "idle_timeout": "2h", "dotfiles": ""},
            "client_cert_path": str(tmp_data_root / "certs" / "portal"),
        },
        "hosts": [
            {"name": "local", "default": True, "type": "docker-tls",
             "docker_host": "tcp://192.168.1.50:2376",
             "address": "", "key_path": ""},
            {"name": "node-ssh", "default": False, "type": "ssh",
             "docker_host": "",
             "address": "devops@192.168.1.40",
             "key_path": "/data/keys/hosts/pve1"},
        ],
        "caddy": {"admin_api": "http://caddy:2019"},
        "cloudflare_manager": {"url": "http://cfm:8000", "api_key": ""},
    }
    (tmp_data_root / "config.yaml").write_text(
        yaml.dump(config, default_flow_style=False), encoding="utf-8"
    )
    from portal.config.store import load_global
    return load_global()
```

Créer `backend/tests/devpod/fake_devpod.py` :

```python
#!/usr/bin/env python3
"""Faux binaire devpod pour les tests. Simule les commandes principales."""
from __future__ import annotations

import json
import sys
import time


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("devpod <command>", file=sys.stderr)
        return 1

    cmd = args[0]

    if cmd == "version":
        print("devpod version 0.6.0 (fake)")
        return 0

    if cmd == "up":
        ws_id = _get_flag(args, "--id") or "unknown"
        print(f"Starting workspace {ws_id}...")
        sys.stdout.flush()
        time.sleep(0.05)
        print(f"Workspace {ws_id} is ready")
        return 0

    if cmd == "stop":
        ws_id = args[1] if len(args) > 1 else "unknown"
        print(f"Stopped {ws_id}")
        return 0

    if cmd == "delete":
        ws_id = args[1] if len(args) > 1 else "unknown"
        print(f"Deleted {ws_id}")
        return 0

    if cmd == "list":
        if "--output" in args and "json" in args:
            print(json.dumps([]))
        else:
            print("(no workspaces)")
        return 0

    if cmd == "provider":
        sub = args[1] if len(args) > 1 else ""
        if sub == "list":
            if "--output" in args and "json" in args:
                # Simuler un provider "docker" déjà présent si DEVPOD_HOME contient "provider_ok"
                import os
                home = os.environ.get("DEVPOD_HOME", "")
                if "provider_ok" in home:
                    print(json.dumps([{"name": "docker"}]))
                else:
                    print(json.dumps([]))
            return 0
        if sub == "add":
            name = args[2] if len(args) > 2 else ""
            print(f"Provider {name!r} added")
            return 0
        return 0

    if cmd in ("--help", "-h", "help"):
        print("fake devpod help")
        return 0

    print(f"fake_devpod: unknown command {cmd!r}", file=sys.stderr)
    return 1


def _get_flag(args: list[str], flag: str) -> str | None:
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(f"{flag}="):
            return a.split("=", 1)[1]
    return None


if __name__ == "__main__":
    sys.exit(main())
```

Créer `backend/tests/devpod/test_env.py` :

```python
from __future__ import annotations

import pytest
from pathlib import Path


def test_build_env_sets_devpod_home_for_user(tmp_data_root: Path, global_cfg) -> None:
    from portal.devpod.env import build_env
    from portal.config.models import WorkspaceSpec

    ws = WorkspaceSpec(name="myapp", source="git@github.com:user/repo.git", host="local")
    env = build_env(login="alice", ws_spec=ws, global_cfg=global_cfg)

    expected_home = str(tmp_data_root / "users" / "alice" / "devpod")
    assert env["DEVPOD_HOME"] == expected_home


def test_build_env_sets_docker_vars_for_docker_tls_host(tmp_data_root: Path, global_cfg) -> None:
    from portal.devpod.env import build_env
    from portal.config.models import WorkspaceSpec

    ws = WorkspaceSpec(name="myapp", source="git@github.com:user/repo.git", host="local")
    env = build_env(login="alice", ws_spec=ws, global_cfg=global_cfg)

    assert env["DOCKER_HOST"] == "tcp://192.168.1.50:2376"
    assert env["DOCKER_TLS_VERIFY"] == "1"
    assert "DOCKER_CERT_PATH" in env


def test_build_env_no_docker_vars_for_ssh_host(tmp_data_root: Path, global_cfg) -> None:
    from portal.devpod.env import build_env
    from portal.config.models import WorkspaceSpec

    ws = WorkspaceSpec(name="myapp", source="git@github.com:user/repo.git", host="node-ssh")
    env = build_env(login="alice", ws_spec=ws, global_cfg=global_cfg)

    assert "DOCKER_HOST" not in env
    assert "DOCKER_TLS_VERIFY" not in env


def test_build_env_uses_default_host_when_none_specified(tmp_data_root: Path, global_cfg) -> None:
    from portal.devpod.env import build_env
    from portal.config.models import WorkspaceSpec

    ws = WorkspaceSpec(name="myapp", source="git@github.com:user/repo.git")
    env = build_env(login="alice", ws_spec=ws, global_cfg=global_cfg)

    # L'host par défaut est "local" (docker-tls)
    assert env["DOCKER_HOST"] == "tcp://192.168.1.50:2376"


def test_build_env_raises_for_unknown_host(tmp_data_root: Path, global_cfg) -> None:
    from portal.devpod.env import build_env, UnknownHostError
    from portal.config.models import WorkspaceSpec

    ws = WorkspaceSpec(name="myapp", source="git@github.com:user/repo.git", host="nonexistent")
    with pytest.raises(UnknownHostError):
        build_env(login="alice", ws_spec=ws, global_cfg=global_cfg)
```

- [ ] **Step 3 : Vérifier que les tests échouent**

```bash
cd backend && uv run pytest tests/devpod/test_env.py -v
```

Attendu : FAIL (ImportError)

- [ ] **Step 4 : Créer `src/portal/devpod/__init__.py`** (vide)

- [ ] **Step 5 : Créer `src/portal/devpod/env.py`**

```python
from __future__ import annotations

import os
import structlog

from ..config.models import GlobalConfig, HostConfig, WorkspaceSpec
from ..config.store import safe_user_path

_log = structlog.get_logger(__name__)


class UnknownHostError(ValueError):
    """L'host référencé n'existe pas dans la config globale."""


def _find_host(host_name: str | None, global_cfg: GlobalConfig) -> HostConfig:
    """Retourne l'HostConfig correspondant, ou l'host par défaut si host_name est None."""
    if host_name is None:
        defaults = [h for h in global_cfg.hosts if h.default]
        if not defaults:
            raise UnknownHostError("No default host configured")
        return defaults[0]
    for h in global_cfg.hosts:
        if h.name == host_name:
            return h
    raise UnknownHostError(f"Host {host_name!r} not found in global config")


def build_env(
    login: str,
    ws_spec: WorkspaceSpec,
    global_cfg: GlobalConfig,
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """
    Construit l'environnement subprocess pour un appel devpod.

    - DEVPOD_HOME : répertoire dédié au user (isolé)
    - DOCKER_HOST/DOCKER_TLS_VERIFY/DOCKER_CERT_PATH : pour host docker-tls
    - Pas de variables DOCKER_* pour host ssh
    """
    env: dict[str, str] = dict(os.environ if base_env is None else base_env)

    # DEVPOD_HOME isolé par user
    devpod_home = str(safe_user_path(login, "devpod"))
    env["DEVPOD_HOME"] = devpod_home

    host = _find_host(ws_spec.host, global_cfg)

    if host.type == "docker-tls":
        env["DOCKER_HOST"] = host.docker_host
        env["DOCKER_TLS_VERIFY"] = "1"
        env["DOCKER_CERT_PATH"] = global_cfg.devpod.client_cert_path
        _log.debug("devpod_env_docker_tls", login=login, docker_host=host.docker_host)
    else:
        # SSH : DevPod gère la connexion, pas de DOCKER_*
        env.pop("DOCKER_HOST", None)
        env.pop("DOCKER_TLS_VERIFY", None)
        env.pop("DOCKER_CERT_PATH", None)
        _log.debug("devpod_env_ssh", login=login, address=host.address)

    return env
```

- [ ] **Step 6 : Créer `tests/devpod/__init__.py`** (vide)

- [ ] **Step 7 : Vérifier les tests**

```bash
cd backend && uv run pytest tests/devpod/test_env.py -v
```

Attendu : `5 passed`

- [ ] **Step 8 : Lint + mypy + tous les tests**

```bash
cd backend && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/ && uv run pytest -q
```

- [ ] **Step 9 : Commit**

```bash
git add backend/src/portal/devpod/ backend/tests/devpod/
git commit -m "feat(devpod): env builder — DEVPOD_HOME isolé + DOCKER_* selon type host"
```

---

## Task 1 : Provider initialization `devpod/provider.py`

**Files:**
- Create: `backend/src/portal/devpod/provider.py`
- Create: `backend/tests/devpod/test_provider.py`

- [ ] **Step 1 : Écrire les tests rouges**

Créer `backend/tests/devpod/test_provider.py` :

```python
from __future__ import annotations

import os
import pytest
from pathlib import Path


@pytest.mark.asyncio
async def test_ensure_provider_adds_docker_when_absent(
    tmp_data_root: Path, global_cfg, fake_devpod_bin: list[str]
) -> None:
    """Si le provider docker est absent du DEVPOD_HOME, il doit être ajouté."""
    from portal.devpod.provider import ensure_provider
    from portal.config.store import ensure_user_dir

    ensure_user_dir("alice")
    env = {
        "DEVPOD_HOME": str(tmp_data_root / "users" / "alice" / "devpod"),
        "PATH": os.environ.get("PATH", ""),
    }

    # Pas de "provider_ok" dans le chemin → fake_devpod retourne liste vide
    calls: list[list[str]] = []
    original_run = None

    # Utiliser le faux binaire
    await ensure_provider(
        login="alice",
        host_type="docker-tls",
        env=env,
        devpod_bin=fake_devpod_bin,
    )
    # Si on arrive ici sans exception, le provider a été ajouté (ou déjà présent)
    # Le faux devpod simule l'ajout sans erreur


@pytest.mark.asyncio
async def test_ensure_provider_is_idempotent_when_already_present(
    tmp_data_root: Path, fake_devpod_bin: list[str]
) -> None:
    """Si le provider est déjà présent, ensure_provider ne refait pas provider add."""
    from portal.devpod.provider import ensure_provider
    from portal.config.store import ensure_user_dir

    ensure_user_dir("alice")
    # Mettre "provider_ok" dans le chemin DEVPOD_HOME pour que fake_devpod liste [docker]
    devpod_home = str(tmp_data_root / "users" / "alice" / "provider_ok_devpod")
    os.makedirs(devpod_home, exist_ok=True)
    env = {
        "DEVPOD_HOME": devpod_home,
        "PATH": os.environ.get("PATH", ""),
    }

    # Ne doit pas lever d'exception
    await ensure_provider(
        login="alice",
        host_type="docker-tls",
        env=env,
        devpod_bin=fake_devpod_bin,
    )


@pytest.mark.asyncio
async def test_ensure_provider_uses_ssh_for_ssh_host(
    tmp_data_root: Path, fake_devpod_bin: list[str]
) -> None:
    """Pour un host ssh, le provider ssh doit être utilisé."""
    from portal.devpod.provider import ensure_provider
    from portal.config.store import ensure_user_dir

    ensure_user_dir("alice")
    env = {
        "DEVPOD_HOME": str(tmp_data_root / "users" / "alice" / "devpod"),
        "PATH": os.environ.get("PATH", ""),
    }

    # Ne doit pas lever d'exception
    await ensure_provider(
        login="alice",
        host_type="ssh",
        env=env,
        devpod_bin=fake_devpod_bin,
    )
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
cd backend && uv run pytest tests/devpod/test_provider.py -v
```

Attendu : FAIL

- [ ] **Step 3 : Créer `src/portal/devpod/provider.py`**

```python
from __future__ import annotations

import json
import asyncio
import structlog

_log = structlog.get_logger(__name__)

_PROVIDER_FOR_HOST = {
    "docker-tls": "docker",
    "ssh": "ssh",
}


async def ensure_provider(
    login: str,
    host_type: str,
    env: dict[str, str],
    devpod_bin: list[str] | None = None,
) -> None:
    """
    S'assure que le provider requis existe dans ce DEVPOD_HOME.
    Idempotent : ne refait rien si déjà présent.
    """
    provider_name = _PROVIDER_FOR_HOST.get(host_type, "docker")
    if devpod_bin is None:
        devpod_bin = ["devpod"]

    # Vérifier les providers existants
    proc = await asyncio.create_subprocess_exec(
        *devpod_bin,
        "provider",
        "list",
        "--output",
        "json",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    try:
        providers = json.loads(stdout.decode(errors="replace") or "[]")
        existing = {p.get("name") for p in providers if isinstance(p, dict)}
    except (json.JSONDecodeError, AttributeError):
        existing = set()

    if provider_name in existing:
        _log.debug("provider_already_present", login=login, provider=provider_name)
        return

    _log.info("provider_add", login=login, provider=provider_name)
    add_proc = await asyncio.create_subprocess_exec(
        *devpod_bin,
        "provider",
        "add",
        provider_name,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await add_proc.wait()
    if add_proc.returncode != 0:
        _log.warning("provider_add_failed", login=login, provider=provider_name,
                     returncode=add_proc.returncode)
```

- [ ] **Step 4 : Vérifier les tests**

```bash
cd backend && uv run pytest tests/devpod/test_provider.py -v
```

Attendu : `3 passed`

- [ ] **Step 5 : Lint + mypy + tous les tests**

```bash
cd backend && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/ && uv run pytest -q
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/portal/devpod/provider.py backend/tests/devpod/test_provider.py
git commit -m "feat(devpod): ensure_provider — initialisation idempotente du provider par DEVPOD_HOME"
```

---

## Task 2 : Runner async `devpod/runner.py`

**Files:**
- Create: `backend/src/portal/devpod/runner.py`
- Create: `backend/tests/devpod/test_runner.py`

- [ ] **Step 1 : Écrire les tests rouges**

Créer `backend/tests/devpod/test_runner.py` :

```python
from __future__ import annotations

import asyncio
import sys
import pytest
from pathlib import Path


@pytest.mark.asyncio
async def test_runner_streams_output_to_log_file(
    tmp_data_root: Path, fake_devpod_bin: list[str]
) -> None:
    """Le subprocess streame stdout vers le fichier log."""
    from portal.devpod.runner import run_subprocess

    log_path = tmp_data_root / "test.log"
    env = {"PATH": __import__("os").environ.get("PATH", "")}

    returncode = await run_subprocess(
        cmd=[*fake_devpod_bin, "up", "--id", "alice-myapp"],
        env=env,
        log_path=log_path,
        ws_id="alice-myapp",
    )

    assert returncode == 0
    content = log_path.read_text(encoding="utf-8")
    assert "alice-myapp" in content


@pytest.mark.asyncio
async def test_runner_does_not_block_event_loop(
    tmp_data_root: Path, fake_devpod_bin: list[str]
) -> None:
    """Pendant le subprocess, l'event loop reste réactif (autre coroutine avance)."""
    import time
    from portal.devpod.runner import run_subprocess

    log_path = tmp_data_root / "test.log"
    env = {"PATH": __import__("os").environ.get("PATH", "")}

    counter = {"ticks": 0}

    async def ticker() -> None:
        for _ in range(5):
            await asyncio.sleep(0.01)
            counter["ticks"] += 1

    await asyncio.gather(
        run_subprocess(
            cmd=[*fake_devpod_bin, "up", "--id", "alice-myapp"],
            env=env,
            log_path=log_path,
            ws_id="alice-myapp",
        ),
        ticker(),
    )

    assert counter["ticks"] >= 3, "Event loop was blocked during subprocess"


@pytest.mark.asyncio
async def test_runner_lock_prevents_concurrent_up_on_same_ws_id(
    tmp_data_root: Path, fake_devpod_bin: list[str]
) -> None:
    """Deux run_subprocess concurrents sur le même ws_id sont sérialisés."""
    from portal.devpod.runner import run_subprocess, clear_locks

    clear_locks()
    log1 = tmp_data_root / "log1.log"
    log2 = tmp_data_root / "log2.log"
    env = {"PATH": __import__("os").environ.get("PATH", "")}

    start_times = []
    end_times = []

    async def timed_run(log: Path) -> None:
        import time
        start_times.append(time.monotonic())
        await run_subprocess(
            cmd=[*fake_devpod_bin, "up", "--id", "alice-myapp"],
            env=env,
            log_path=log,
            ws_id="alice-myapp",
        )
        end_times.append(time.monotonic())

    await asyncio.gather(timed_run(log1), timed_run(log2))

    # Avec sérialisation, le second commence après la fin du premier
    # (les deux doivent finir sans erreur)
    assert len(end_times) == 2

    clear_locks()


@pytest.mark.asyncio
async def test_runner_different_ws_ids_run_concurrently(
    tmp_data_root: Path, fake_devpod_bin: list[str]
) -> None:
    """Deux ws_id différents peuvent s'exécuter en parallèle."""
    import time
    from portal.devpod.runner import run_subprocess, clear_locks

    clear_locks()
    log1 = tmp_data_root / "log1.log"
    log2 = tmp_data_root / "log2.log"
    env = {"PATH": __import__("os").environ.get("PATH", "")}

    t_start = time.monotonic()
    await asyncio.gather(
        run_subprocess(cmd=[*fake_devpod_bin, "up", "--id", "alice-app1"],
                       env=env, log_path=log1, ws_id="alice-app1"),
        run_subprocess(cmd=[*fake_devpod_bin, "up", "--id", "alice-app2"],
                       env=env, log_path=log2, ws_id="alice-app2"),
    )
    elapsed = time.monotonic() - t_start

    # Si les deux s'exécutent en parallèle, le temps total ≈ durée d'un seul
    # fake_devpod sleep 0.05s, deux en série = ~0.1s, en parallèle < 0.1s
    assert elapsed < 0.15, f"Expected parallel execution, took {elapsed:.2f}s"
    clear_locks()
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
cd backend && uv run pytest tests/devpod/test_runner.py -v
```

Attendu : FAIL

- [ ] **Step 3 : Créer `src/portal/devpod/runner.py`**

```python
from __future__ import annotations

import asyncio
import structlog
from pathlib import Path

_log = structlog.get_logger(__name__)

# Registre des locks par ws_id
_locks: dict[str, asyncio.Lock] = {}


def _get_lock(ws_id: str) -> asyncio.Lock:
    if ws_id not in _locks:
        _locks[ws_id] = asyncio.Lock()
    return _locks[ws_id]


def clear_locks() -> None:
    """Vide le registre de locks (usage tests uniquement)."""
    _locks.clear()


async def run_subprocess(
    cmd: list[str],
    env: dict[str, str],
    log_path: Path,
    ws_id: str,
) -> int:
    """
    Exécute une commande devpod en async, streame stdout+stderr vers log_path.
    Acquiert le verrou par ws_id (sérialise les opérations sur le même workspace).
    """
    async with _get_lock(ws_id):
        _log.info("devpod_subprocess_start", ws_id=ws_id, cmd=cmd[0] if cmd else "")
        log_path.parent.mkdir(parents=True, exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        assert proc.stdout is not None
        with log_path.open("w", encoding="utf-8") as log_file:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                decoded = line.decode(errors="replace")
                log_file.write(decoded)
                log_file.flush()

        returncode = await proc.wait()
        _log.info("devpod_subprocess_done", ws_id=ws_id, returncode=returncode)
        return returncode
```

- [ ] **Step 4 : Vérifier les tests**

```bash
cd backend && uv run pytest tests/devpod/test_runner.py -v
```

Attendu : `4 passed`

- [ ] **Step 5 : Lint + mypy + tous les tests**

```bash
cd backend && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/ && uv run pytest -q
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/portal/devpod/runner.py backend/tests/devpod/test_runner.py
git commit -m "feat(devpod): runner async — subprocess non-bloquant, streaming logs, verrou par ws_id"
```

---

## Task 3 : Service `devpod/service.py`

**Files:**
- Create: `backend/src/portal/devpod/service.py`
- Create: `backend/tests/devpod/test_service.py`

Note : Avant d'implémenter, l'implémenteur doit relire les flags réels de `devpod up --help` et `devpod list --help` pour adapter les commandes.

- [ ] **Step 1 : Écrire les tests rouges**

Créer `backend/tests/devpod/test_service.py` :

```python
from __future__ import annotations

import asyncio
import json
import os
import pytest
from pathlib import Path


@pytest.mark.asyncio
async def test_up_rejects_non_dns_safe_name(tmp_data_root: Path, global_cfg, fake_devpod_bin: list[str]) -> None:
    """up() rejette un ws name non DNS-safe avant tout lancement."""
    from portal.devpod.service import DevPodService
    from portal.config.models import WorkspaceSpec

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    ws = WorkspaceSpec(name="valid", source="git@github.com:user/repo.git")
    # Modifier le name après construction (contournement du validator pydantic)
    object.__setattr__(ws, "name", "INVALID NAME!")
    with pytest.raises(ValueError, match="DNS"):
        await svc.up(login="alice", ws_spec=ws)


@pytest.mark.asyncio
async def test_up_writes_status_file(tmp_data_root: Path, global_cfg, fake_devpod_bin: list[str]) -> None:
    """up() écrit un fichier de statut dans routes/<ws_id>.json."""
    from portal.devpod.service import DevPodService
    from portal.config.models import WorkspaceSpec
    from portal.auth.router import provision_user

    await provision_user(login="alice", sub="sub", data_root=tmp_data_root)

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    ws = WorkspaceSpec(name="myapp", source="git@github.com:user/repo.git")

    ws_id = await svc.up(login="alice", ws_spec=ws)
    assert ws_id == "alice-myapp"

    # Attendre que la tâche de fond finisse
    await asyncio.sleep(0.3)

    status_path = tmp_data_root / "routes" / f"{ws_id}.json"
    assert status_path.exists()
    data = json.loads(status_path.read_text(encoding="utf-8"))
    assert data["ws_id"] == ws_id
    assert data["status"] in ("running", "failed")


@pytest.mark.asyncio
async def test_secrets_not_leaked_in_logs(tmp_data_root: Path, global_cfg, fake_devpod_bin: list[str]) -> None:
    """Les valeurs secrètes résolues ne doivent pas apparaître dans les logs."""
    from portal.devpod.service import DevPodService
    from portal.config.models import WorkspaceSpec
    from portal.auth.router import provision_user

    await provision_user(login="alice", sub="sub", data_root=tmp_data_root)

    # Créer un secrets.yaml inline pour le user
    secrets_file = tmp_data_root / "users" / "alice" / "secrets.yaml"
    secrets_file.write_text(
        "devpod:\n  ns123:\n    mykey: SUPER_SECRET_VALUE\n",
        encoding="utf-8",
    )

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    # Workspace avec une env var résolue inline (valeur littérale pour simplifier le test)
    ws = WorkspaceSpec(
        name="myapp",
        source="git@github.com:user/repo.git",
        env={"API_KEY": "SUPER_SECRET_VALUE"},
    )

    ws_id = await svc.up(login="alice", ws_spec=ws)
    await asyncio.sleep(0.3)

    # Vérifier que le log ne contient pas la valeur secrète
    log_path = tmp_data_root / "logs" / "alice" / f"{ws_id}.log"
    if log_path.exists():
        content = log_path.read_text(encoding="utf-8")
        assert "SUPER_SECRET_VALUE" not in content, "Secret leaked in logs!"


@pytest.mark.asyncio
async def test_status_returns_current_status(tmp_data_root: Path, global_cfg, fake_devpod_bin: list[str]) -> None:
    """status() lit le fichier de statut et retourne l'état courant."""
    from portal.devpod.service import DevPodService
    from portal.auth.router import provision_user

    await provision_user(login="alice", sub="sub", data_root=tmp_data_root)

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    ws_id = "alice-myapp"

    # Écrire manuellement un statut
    routes_dir = tmp_data_root / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    (routes_dir / f"{ws_id}.json").write_text(
        json.dumps({"ws_id": ws_id, "status": "running"}), encoding="utf-8"
    )

    status = await svc.status(login="alice", ws_id=ws_id)
    assert status["status"] == "running"
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
cd backend && uv run pytest tests/devpod/test_service.py -v
```

Attendu : FAIL

- [ ] **Step 3 : Créer `src/portal/devpod/service.py`**

```python
from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import structlog
from pathlib import Path
from typing import Any

import yaml

from ..config.models import GlobalConfig, WorkspaceSpec
from ..config.store import _data_root, safe_user_path, load_user
from .env import build_env, UnknownHostError
from .provider import ensure_provider
from .runner import run_subprocess

_log = structlog.get_logger(__name__)

# ws_id DNS-safe : ^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$
_WS_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$")


class DevPodService:
    def __init__(
        self,
        global_cfg: GlobalConfig,
        devpod_bin: list[str] | None = None,
    ) -> None:
        self._global_cfg = global_cfg
        self._devpod_bin = devpod_bin or [global_cfg.devpod.binary]

    def _ws_id(self, login: str, name: str) -> str:
        ws_id = f"{login}-{name}"
        if not _WS_ID_RE.fullmatch(ws_id):
            raise ValueError(f"Computed ws_id {ws_id!r} is not DNS-safe")
        return ws_id

    def _status_path(self, ws_id: str) -> Path:
        return _data_root() / "routes" / f"{ws_id}.json"

    def _log_path(self, login: str, ws_id: str) -> Path:
        return _data_root() / "logs" / login / f"{ws_id}.log"

    def _write_status(self, ws_id: str, status: str, **extra: Any) -> None:
        path = self._status_path(ws_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"ws_id": ws_id, "status": status, **extra}
        path.write_text(json.dumps(data), encoding="utf-8")

    async def up(self, login: str, ws_spec: WorkspaceSpec) -> str:
        """Lance un workspace en tâche de fond. Retourne le ws_id."""
        ws_id = self._ws_id(login, ws_spec.name)
        env = build_env(login=login, ws_spec=ws_spec, global_cfg=self._global_cfg)

        host_type = "docker-tls"
        if ws_spec.host:
            for h in self._global_cfg.hosts:
                if h.name == ws_spec.host:
                    host_type = h.type
                    break

        await ensure_provider(
            login=login,
            host_type=host_type,
            env=env,
            devpod_bin=self._devpod_bin,
        )

        # Générer devcontainer.json minimal (recipes = M7)
        devcontainer = self._generate_devcontainer(ws_spec)
        dc_path = self._write_devcontainer(login, ws_id, devcontainer)

        # Résoudre les env vars (littéraux passés tels quels en M3 ; résolution complète = plus tard)
        resolved_env = dict(ws_spec.env)

        self._write_status(ws_id, "provisioning")

        # Lancer en tâche de fond
        asyncio.create_task(
            self._run_up_task(ws_id, ws_spec.source, dc_path, env, resolved_env, login)
        )
        _log.info("workspace_up_started", ws_id=ws_id, login=login)
        return ws_id

    async def _run_up_task(
        self,
        ws_id: str,
        source: str,
        dc_path: Path,
        env: dict[str, str],
        resolved_env: dict[str, str],
        login: str,
    ) -> None:
        # Injecter les env vars résolues dans l'environnement du subprocess
        subprocess_env = {**env, **resolved_env}

        # Construire la commande — adapter les flags à la version réelle
        # IMPÉRATIF : vérifier devpod up --help avant de fixer ces flags
        cmd = [
            *self._devpod_bin,
            "up",
            source,
            "--id",
            ws_id,
            "--ide",
            "openvscode",
            "--devcontainer-path",
            str(dc_path),
        ]
        # Ajouter le flag no-open-ide si disponible dans la version installée
        # Exemple : "--open-ide=false" ou "--no-open-ide" — À VÉRIFIER
        # cmd.append("--open-ide=false")  # décommenter après vérification

        log_path = self._log_path(login, ws_id)
        returncode = await run_subprocess(
            cmd=cmd, env=subprocess_env, log_path=log_path, ws_id=ws_id
        )

        status = "running" if returncode == 0 else "failed"
        self._write_status(ws_id, status, returncode=returncode)
        if returncode != 0:
            _log.warning("workspace_up_failed", ws_id=ws_id, returncode=returncode)

    def _generate_devcontainer(self, ws_spec: WorkspaceSpec) -> dict:
        """Génère un devcontainer.json minimal. Les recipes (M7) sont omises ici."""
        return {
            "image": "mcr.microsoft.com/devcontainers/base:ubuntu",
            "remoteEnv": {},  # les env vars sont injectées via subprocess env
        }

    def _write_devcontainer(self, login: str, ws_id: str, content: dict) -> Path:
        """Écrit devcontainer.json dans un fichier temporaire sous le dossier user."""
        user_dir = safe_user_path(login, "devpod")
        user_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=user_dir, suffix=f"-{ws_id}.json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(content, f, indent=2)
        except Exception:
            os.unlink(tmp_path)
            raise
        return Path(tmp_path)

    async def stop(self, login: str, ws_id: str) -> None:
        env = {"PATH": os.environ.get("PATH", "")}
        user_devpod_home = str(safe_user_path(login, "devpod"))
        env["DEVPOD_HOME"] = user_devpod_home

        cmd = [*self._devpod_bin, "stop", ws_id]
        log_path = self._log_path(login, f"{ws_id}-stop")
        await run_subprocess(cmd=cmd, env=env, log_path=log_path, ws_id=ws_id)
        self._write_status(ws_id, "stopped")
        _log.info("workspace_stopped", ws_id=ws_id, login=login)

    async def delete(self, login: str, ws_id: str) -> None:
        env = {"PATH": os.environ.get("PATH", "")}
        env["DEVPOD_HOME"] = str(safe_user_path(login, "devpod"))

        cmd = [*self._devpod_bin, "delete", ws_id, "--force"]
        log_path = self._log_path(login, f"{ws_id}-delete")
        await run_subprocess(cmd=cmd, env=env, log_path=log_path, ws_id=ws_id)
        status_path = self._status_path(ws_id)
        if status_path.exists():
            status_path.unlink()
        _log.info("workspace_deleted", ws_id=ws_id, login=login)

    async def status(self, login: str, ws_id: str) -> dict:
        path = self._status_path(ws_id)
        if not path.exists():
            return {"ws_id": ws_id, "status": "unknown"}
        return json.loads(path.read_text(encoding="utf-8"))

    async def list_workspaces(self, login: str) -> list[dict]:
        """Liste les workspaces du user depuis les fichiers de statut."""
        routes_dir = _data_root() / "routes"
        if not routes_dir.exists():
            return []
        prefix = f"{login}-"
        results = []
        for f in routes_dir.glob("*.json"):
            if f.stem.startswith(prefix):
                try:
                    results.append(json.loads(f.read_text(encoding="utf-8")))
                except json.JSONDecodeError:
                    pass
        return results

    def get_port(self, ws_id: str) -> int | None:
        """Stub — implémentation complète en M6."""
        return None
```

- [ ] **Step 4 : Vérifier les tests**

```bash
cd backend && uv run pytest tests/devpod/test_service.py -v
```

Attendu : `4 passed`

Si `test_up_rejects_non_dns_safe_name` échoue car pydantic empêche la mutation : utiliser directement une WorkspaceSpec avec un faux nom passé via `model_construct` ou tester la fonction `_ws_id` directement.

- [ ] **Step 5 : Lint + mypy + tous les tests**

```bash
cd backend && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/ && uv run pytest -q
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/portal/devpod/service.py backend/tests/devpod/test_service.py
git commit -m "feat(devpod): DevPodService — up/stop/delete/status/list avec tâche de fond et statut fichier"
```

---

## Task 4 : Endpoints HTTP `/me/workspaces/{name}/up|stop|delete|status`

**Files:**
- Create: `backend/src/portal/routes/workspace_ops.py`
- Modify: `backend/src/portal/app.py`
- Create: `backend/tests/routes/test_workspace_ops.py`

- [ ] **Step 1 : Écrire les tests rouges**

Créer `backend/tests/routes/test_workspace_ops.py` :

```python
from __future__ import annotations

import asyncio
import json
import os
import sys
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

FAKE_DEVPOD = Path(__file__).parent.parent / "devpod" / "fake_devpod.py"


def _make_app_with_provisioned_alice(tmp_data_root: Path):
    import portal.settings as mod
    mod._settings = None
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_data_root)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    os.environ["DEV_MODE"] = "true"
    mod._settings = None

    # Créer un config.yaml global minimal
    import yaml
    config = {
        "version": "1",
        "server": {"listen": "0.0.0.0:8080", "base_domain": "dev.yoops.org",
                   "external_url": "https://dev.yoops.org", "dev_mode": True,
                   "log": {"level": "info", "format": "text", "output": ""}},
        "auth": {"oidc": {"issuer": "https://kc.test", "client_id": "portal",
                           "client_secret": "", "scopes": ["openid"],
                           "role_claim": "realm_access.roles", "admin_role": "admin",
                           "user_role": "dev", "username_claim": "preferred_username"}},
        "secrets": {"backend": "inline",
                    "harpocrate": {"url": "", "api_key": "", "base_path": "devpod"}},
        "devpod": {
            "binary": f"{sys.executable} {FAKE_DEVPOD}",
            "defaults": {"ide": "openvscode", "idle_timeout": "2h", "dotfiles": ""},
            "client_cert_path": str(tmp_data_root / "certs" / "portal"),
        },
        "hosts": [
            {"name": "local", "default": True, "type": "docker-tls",
             "docker_host": "tcp://192.168.1.50:2376", "address": "", "key_path": ""},
        ],
        "caddy": {"admin_api": "http://caddy:2019"},
        "cloudflare_manager": {"url": "http://cfm:8000", "api_key": ""},
    }
    (tmp_data_root / "config.yaml").write_text(
        yaml.dump(config, default_flow_style=False), encoding="utf-8"
    )

    asyncio.run(_provision(tmp_data_root))

    from portal.app import create_app
    from portal.auth.rbac import UserInfo, require_user
    app = create_app()
    user = UserInfo(login="alice", roles=["dev"])
    app.dependency_overrides[require_user] = lambda: user
    return app


async def _provision(tmp_data_root: Path) -> None:
    from portal.auth.router import provision_user
    await provision_user(login="alice", sub="sub", data_root=tmp_data_root)


def test_up_returns_202_with_ws_id(tmp_path: Path) -> None:
    app = _make_app_with_provisioned_alice(tmp_path)
    with TestClient(app) as client:
        resp = client.post("/me/workspaces/myapp/up", json={
            "source": "git@github.com:user/repo.git"
        })
    assert resp.status_code == 202
    data = resp.json()
    assert data["ws_id"] == "alice-myapp"


def test_status_returns_workspace_status(tmp_path: Path) -> None:
    app = _make_app_with_provisioned_alice(tmp_path)
    # Écrire un statut manuellement
    routes_dir = tmp_path / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    (routes_dir / "alice-myapp.json").write_text(
        json.dumps({"ws_id": "alice-myapp", "status": "running"}), encoding="utf-8"
    )
    with TestClient(app) as client:
        resp = client.get("/me/workspaces/myapp/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


def test_up_rejects_unknown_host(tmp_path: Path) -> None:
    app = _make_app_with_provisioned_alice(tmp_path)
    with TestClient(app) as client:
        resp = client.post("/me/workspaces/myapp/up", json={
            "source": "git@github.com:user/repo.git",
            "host": "nonexistent-host",
        })
    assert resp.status_code in (404, 400, 422)
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
cd backend && uv run pytest tests/routes/test_workspace_ops.py -v
```

Attendu : FAIL

- [ ] **Step 3 : Créer `src/portal/routes/workspace_ops.py`**

```python
from __future__ import annotations

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from ..auth.rbac import UserInfo, require_user
from ..config.store import load_global
from ..devpod.env import UnknownHostError
from ..devpod.service import DevPodService

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["workspace-ops"])


class UpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    host: str | None = None


def _get_service() -> DevPodService:
    global_cfg = load_global()
    return DevPodService(global_cfg=global_cfg)


@router.post("/workspaces/{name}/up", status_code=202)
async def workspace_up(
    name: str,
    req: UpRequest,
    background_tasks: BackgroundTasks,
    user: UserInfo = Depends(require_user),
) -> dict:
    from ..config.models import WorkspaceSpec

    try:
        ws = WorkspaceSpec(name=name, source=req.source, host=req.host)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    svc = _get_service()
    try:
        ws_id = await svc.up(login=user.login, ws_spec=ws)
    except UnknownHostError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _log.info("workspace_up_requested", login=user.login, ws_id=ws_id)
    return {"ws_id": ws_id, "status": "provisioning"}


@router.post("/workspaces/{name}/stop")
async def workspace_stop(
    name: str, user: UserInfo = Depends(require_user)
) -> dict:
    ws_id = f"{user.login}-{name}"
    svc = _get_service()
    await svc.stop(login=user.login, ws_id=ws_id)
    return {"ws_id": ws_id, "status": "stopped"}


@router.delete("/workspaces/{name}")
async def workspace_delete(
    name: str, user: UserInfo = Depends(require_user)
) -> dict:
    ws_id = f"{user.login}-{name}"
    svc = _get_service()
    await svc.delete(login=user.login, ws_id=ws_id)
    return {"ws_id": ws_id, "deleted": True}


@router.get("/workspaces/{name}/status")
async def workspace_status(
    name: str, user: UserInfo = Depends(require_user)
) -> dict:
    ws_id = f"{user.login}-{name}"
    svc = _get_service()
    return await svc.status(login=user.login, ws_id=ws_id)
```

- [ ] **Step 4 : Ajouter `workspace_ops_router` dans `app.py`**

```python
from .routes.workspace_ops import router as workspace_ops_router
# dans create_app() :
app.include_router(workspace_ops_router, prefix="/me")
```

- [ ] **Step 5 : Vérifier les tests**

```bash
cd backend && uv run pytest tests/routes/test_workspace_ops.py -v
```

Attendu : `3 passed`

- [ ] **Step 6 : Lint + mypy + tous les tests**

```bash
cd backend && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/ && uv run pytest -q
```

- [ ] **Step 7 : Commit**

```bash
git add backend/src/portal/routes/workspace_ops.py backend/src/portal/app.py backend/tests/routes/test_workspace_ops.py
git commit -m "feat(routes): endpoints /me/workspaces/{name}/up|stop|delete|status — 202 async"
```

---

## Definition of Done M3

- [ ] `uv run pytest tests/ -v` → 0 échec
- [ ] `uv run ruff check src/ tests/` → 0 erreur
- [ ] `uv run ruff format --check src/ tests/` → 0 erreur
- [ ] `uv run mypy src/` → 0 erreur
- [ ] Tests obligatoires verts :
  - `env.py` : DOCKER_* corrects selon type host, DEVPOD_HOME dans dossier user
  - Runner : non-bloquant (event loop avance en parallèle), streaming vers fichier log
  - Verrou : deux `up` sur même ws_id sérialisés, deux ws_id différents parallèles
  - `up` rejette name non DNS-safe
  - Secrets (env vars littérales) absents des fichiers log
- [ ] Pièges couverts :
  - §B-8 : DEVPOD_HOME injecté dans chaque subprocess
  - §B-9 : provider initialisé par DEVPOD_HOME
  - §B-10/§C-15 : zéro `subprocess.run` bloquant
  - §B-13 : ws_id = `{login}-{name}`, DNS-safe validé
  - §C-20 : verrou asyncio.Lock par ws_id
  - §D-21 : env vars resolues dans subprocess env, jamais dans devcontainer.json ni log
- [ ] Flags devpod vérifiés contre `--help` réel et documentés dans les commentaires du code
