# MCP `devpod` — Complément (spec 25) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compléter la surface de pilotage du backend MCP interne `devpod` avec les façades de la Section A, l'infrastructure d'opérations asynchrones (`operations_*`) pilotant `create`/`delete`/`apply_recipe`/`profile_set`, l'harmonisation async des lifecycle de la spec 24, et les primitives `secrets_*` zéro-knowledge.

**Architecture :** On suit le patron de la spec 24 — chaque primitive = une entrée `DEVPOD_PRIMITIVES` (definition + scope) dans `registry.py` + une impl `_<nom>(conn, args, owner_login)` enregistrée dans `_IMPLS` (`__init__.py`). Les impls appellent les services internes (`DevPodService`, `ws_exec`, resolver secrets, config store) — jamais SSH/tmux/Docker en direct (façade I-1). Les opérations longues ne réalisent pas l'action : elles la *lancent* via un runner de fond et retournent `{operation_id}` ; un fichier YAML par opération sous `/data/operations/` porte l'état, lu par `operations_get`/`operations_list`.

**Tech Stack :** Python 3.12, asyncio, pydantic v2, pyyaml, mcp types, pytest + pytest-asyncio, monkeypatch/AsyncMock.

## Global Constraints

- Toutes les impls sont `async def _<nom>(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any` et retournent un objet JSON-sérialisable (le wrapping `_ok`/`_err` est fait par `execute_internal_tool`).
- Erreur métier ⇒ lever `DevpodToolError(message)` (jamais d'exception nue ⇒ pas de 500). Tool inconnu ⇒ `McpError` (déjà géré par le dispatch).
- Tout nom de workspace passe par `_require_ws(args)` ; tout chemin sous le workspace par `safe_workspace_path(name, rel)`. La concaténation de chemins est une faute.
- Le `ws_id` interne est **toujours** `f"{owner_login}-{name}"`.
- Aucune valeur de secret ne transite par une primitive (zéro-knowledge Harpocrate) : `secrets_*` ne manipule que des références `${vault://...}` / `${env://...}`.
- Écriture fichier d'état = `tempfile` dans le même dossier + `os.replace` (atomique, I-6).
- Logs structurés via `structlog.get_logger(__name__)` — jamais `print()`. Pas de secret dans un log.
- `workspace_git_commit` refuse si la branche courante ≠ `dev`.
- Chaque tâche finit par : `uv run ruff check`, `uv run mypy src/`, `uv run pytest` verts, puis commit conventionnel FR.
- Branche de travail : `dev` uniquement.
- Décisions actées (commit `131ba73`) : long-running ⇒ `operations_*` async ; `agent_dispatch` abandonné ; `workspace_delete` garde par flag `confirm:true` ; `secrets_*` référence/injection ; `resources` via `ws_exec` cgroup+df ; `apply_recipe`/`profile_set` = recréation (reprovision) async.

---

## File Structure

**Créés :**
- `backend/src/portal/mcp/devpod_tools/operations.py` — store d'opérations async (modèle, persistance YAML atomique, runner de fond). Responsabilité unique : cycle de vie d'une opération.
- `backend/src/portal/devpod/provision.py` — orchestration de provisioning réutilisable (résolution recettes + secrets + profil + `svc.up`), partagée entre la route REST et la primitive MCP `workspace_create` (DRY).
- Tests : `backend/tests/mcp/test_devpod_facades.py`, `test_devpod_operations.py`, `test_devpod_async_lifecycle.py`, `test_devpod_secrets.py`, `backend/tests/devpod/test_provision.py`.

**Modifiés :**
- `backend/src/portal/mcp/devpod_tools/registry.py` — ajout des definitions (Section A + B + harmonisation) ; passage des lifecycle `start`/`stop`/`restart` en retour `{operation_id}`.
- `backend/src/portal/mcp/devpod_tools/__init__.py` — ajout des impls + entrées `_IMPLS`.
- `backend/src/portal/routes/workspace_ops.py` — `workspace_up` délègue à `provision.provision_workspace` (Task B4).
- La doc produit générée depuis le registre (§6) — régénérée en dernière tâche.

> **Écart assumé vs spec :** `workspace_profile_set` est classé Section A (scope `write`) dans la spec, mais la décision « recréation async » le rend équivalent à une opération longue. Il est donc implémenté dans le Lot B (runner + `operation_id`), pas dans le Lot A. À acter dans la doc produit.

---

# LOT A — Façades synchrones (Section A)

Primitives lecture/exec sans état long : `workspace_get`, `workspace_logs`, `workspace_resources`, `session_interrupt`, `session_close`, `workspace_git_status`, `workspace_git_commit`, `node_list`.

### Task A1: `workspace_get`

**Files:**
- Modify: `backend/src/portal/mcp/devpod_tools/registry.py` (ajout entrée)
- Modify: `backend/src/portal/mcp/devpod_tools/__init__.py` (impl + `_IMPLS`)
- Test: `backend/tests/mcp/test_devpod_facades.py`

**Interfaces:**
- Consumes : `load_user_db(owner_login, conn)` → `cfg.workspaces: list[WorkspaceSpec]` ; `get_service().status(login, ws_id)` → `dict` ; `_session_list(conn, args, owner_login)` (existant) → `list[dict]`.
- Produces : `_workspace_get(conn, args, owner_login) -> dict` retournant `{id, name, repo, branch, status, node, recipe, tags, devcontainer_ref, sessions, created_at}`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/mcp/test_devpod_facades.py
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from portal.mcp import devpod_tools


@pytest.mark.asyncio
async def test_workspace_get_descriptor(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = SimpleNamespace(
        name="dev", source="git@x/y.git", branch="dev", host="node1",
        recipes=["python"], devcontainer_path="", template="",
    )
    cfg = SimpleNamespace(workspaces=[spec])
    monkeypatch.setattr(devpod_tools, "load_user_db", AsyncMock(return_value=cfg))
    svc = SimpleNamespace(status=AsyncMock(return_value={"status": "running", "created_at": "2026-06-01T00:00:00Z"}))
    monkeypatch.setattr(devpod_tools, "get_service", lambda: svc)
    monkeypatch.setattr(devpod_tools, "_session_list", AsyncMock(return_value=[{"name": "main"}]))

    res = await devpod_tools._workspace_get(None, {"workspace": "dev"}, "alice")

    assert res["id"] == "alice-dev"
    assert res["name"] == "dev"
    assert res["repo"] == "git@x/y.git"
    assert res["status"] == "running"
    assert res["node"] == "node1"
    assert res["recipe"] == ["python"]
    assert res["sessions"] == [{"name": "main"}]
    assert res["created_at"] == "2026-06-01T00:00:00Z"


@pytest.mark.asyncio
async def test_workspace_get_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(workspaces=[])
    monkeypatch.setattr(devpod_tools, "load_user_db", AsyncMock(return_value=cfg))
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._workspace_get(None, {"workspace": "ghost"}, "alice")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/mcp/test_devpod_facades.py -k workspace_get -v`
Expected: FAIL (`AttributeError: module ... has no attribute '_workspace_get'`).

- [ ] **Step 3: Add registry definition**

Dans `registry.py`, ajouter à `DEVPOD_PRIMITIVES` :

```python
    "workspace_get": {
        "description": "Retourne le descripteur complet d'un workspace (repo, branche, recette, node, sessions, dates).",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {"workspace": {"type": "string"}},
        },
        "scope": "read",
    },
```

- [ ] **Step 4: Write minimal implementation**

Dans `__init__.py`, ajouter l'impl (et l'entrée `_IMPLS`) :

```python
async def _workspace_get(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    cfg = await load_user_db(owner_login, conn)
    spec = next((s for s in cfg.workspaces if s.name == name), None)
    if spec is None:
        raise DevpodToolError(f"workspace inconnu: {name}")
    ws_id = f"{owner_login}-{name}"
    st = await get_service().status(owner_login, ws_id)
    sessions = await _session_list(conn, {"workspace": name}, owner_login)
    return {
        "id": ws_id,
        "name": spec.name,
        "repo": spec.source,
        "branch": spec.branch or None,
        "status": st.get("status", "unknown"),
        "node": spec.host or None,
        "recipe": spec.recipes,
        "tags": [],
        "devcontainer_ref": spec.devcontainer_path or spec.template or None,
        "sessions": sessions,
        "created_at": st.get("created_at") or st.get("updated_at"),
    }
```

Ajouter dans `_IMPLS` : `"workspace_get": _workspace_get,`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/mcp/test_devpod_facades.py -k workspace_get -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Lint + type**

Run: `cd backend && uv run ruff check src/ tests/ && uv run mypy src/`
Expected: pas d'erreur.

- [ ] **Step 7: Commit**

```bash
git add backend/src/portal/mcp/devpod_tools/registry.py backend/src/portal/mcp/devpod_tools/__init__.py backend/tests/mcp/test_devpod_facades.py
git commit -m "feat(mcp-devpod): workspace_get — descripteur complet (spec 25 §A)"
```

---

### Task A2: `workspace_logs`

**Files:**
- Modify: `registry.py`, `__init__.py`
- Test: `backend/tests/mcp/test_devpod_facades.py`

**Interfaces:**
- Consumes : `_data_root()` (à importer depuis `...config.store`) → `Path` ; `_session_capture(conn, args, owner_login)` (existant) → `{"output": str}`.
- Produces : `_workspace_logs(conn, args, owner_login) -> dict` retournant `{source, output}`.

> **Limitation v1 documentée :** `setup` et `container` lisent tous deux le journal de provisioning du portail (`/data/logs/{login}/{ws_id}.log`) — un seul flux capturé en v1. `agent` capture le pane tmux `main`. Le paramètre `since` est accepté au schéma mais **non appliqué en v1** (réservé, comme `_origin`/`_depth` de la spec 24).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_workspace_logs_setup_reads_portal_log(monkeypatch, tmp_path):
    from pathlib import Path
    logs = tmp_path / "logs" / "alice"
    logs.mkdir(parents=True)
    (logs / "alice-dev.log").write_text("line1\nline2\nline3\n", encoding="utf-8")
    monkeypatch.setattr(devpod_tools, "_data_root", lambda: tmp_path)

    res = await devpod_tools._workspace_logs(None, {"workspace": "dev", "source": "setup", "lines": 2}, "alice")
    assert res["source"] == "setup"
    assert res["output"].splitlines() == ["line2", "line3"]


@pytest.mark.asyncio
async def test_workspace_logs_agent_captures_pane(monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr(devpod_tools, "_session_capture", AsyncMock(return_value={"output": "agent-buf"}))
    res = await devpod_tools._workspace_logs(None, {"workspace": "dev", "source": "agent"}, "alice")
    assert res == {"source": "agent", "output": "agent-buf"}


@pytest.mark.asyncio
async def test_workspace_logs_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(devpod_tools, "_data_root", lambda: tmp_path)
    res = await devpod_tools._workspace_logs(None, {"workspace": "dev", "source": "container"}, "alice")
    assert res == {"source": "container", "output": ""}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/mcp/test_devpod_facades.py -k workspace_logs -v`
Expected: FAIL (`_workspace_logs` non défini).

- [ ] **Step 3: Add registry definition**

```python
    "workspace_logs": {
        "description": "Retourne les logs d'un workspace (setup d'installation, agent ou conteneur).",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {
                "workspace": {"type": "string"},
                "source": {"type": "string", "enum": ["setup", "agent", "container"], "default": "container"},
                "lines": {"type": "integer", "default": 200, "minimum": 1},
                "since": {"type": "string", "description": "Réservé v1 (non appliqué)."},
            },
        },
        "scope": "read",
    },
```

- [ ] **Step 4: Write minimal implementation**

Ajouter en tête de `__init__.py` l'import : `from ...config.store import _data_root` (regrouper avec les imports existants).

```python
async def _workspace_logs(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    source = str(args.get("source", "container"))
    lines = int(args.get("lines", 200))
    if source == "agent":
        cap = await _session_capture(conn, {"workspace": name, "lines": lines}, owner_login)
        return {"source": "agent", "output": cap["output"]}
    # setup / container : journal de provisioning du portail (flux unique en v1).
    ws_id = f"{owner_login}-{name}"
    logs_root = _data_root() / "logs"
    log_file = logs_root / owner_login / f"{ws_id}.log"
    if not log_file.is_relative_to(logs_root) or not log_file.exists():
        return {"source": source, "output": ""}
    text = log_file.read_text(encoding="utf-8", errors="replace")
    tail = "\n".join(text.splitlines()[-lines:])
    return {"source": source, "output": tail}
```

Ajouter `"workspace_logs": _workspace_logs,` dans `_IMPLS`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/mcp/test_devpod_facades.py -k workspace_logs -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Lint + type + commit**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
git add backend/src/portal/mcp/devpod_tools/ backend/tests/mcp/test_devpod_facades.py
git commit -m "feat(mcp-devpod): workspace_logs — setup/agent/container (spec 25 §A)"
```

---

### Task A3: `workspace_resources`

**Files:**
- Modify: `registry.py`, `__init__.py`
- Test: `backend/tests/mcp/test_devpod_facades.py`

**Interfaces:**
- Consumes : `ws_exec(owner_login, ws_id, command, timeout)` (existant) → `tuple[int, str]`.
- Produces : `_workspace_resources(conn, args, owner_login) -> dict` retournant `{cpu_pct, mem_used, mem_limit, disk_used, disk_limit}`.

> Lecture cgroup v2 (`memory.current`, `memory.max`) + `df -B1` du workspace dans le conteneur. `cpu_pct` calculé par double lecture de `cpu.stat` (`usage_usec`) espacée de 100 ms. `mem_limit == "max"` (illimité) ⇒ `None`. Valeurs non lisibles ⇒ `None` (jamais d'exception).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_workspace_resources_parses_cgroup(monkeypatch):
    from unittest.mock import AsyncMock
    # Sortie scriptée : usage1, usage2 (cpu), mem_used, mem_max, df disk_used disk_total
    payload = "1000000\n1050000\n536870912\n1073741824\n2147483648 5368709120\n"
    monkeypatch.setattr(devpod_tools, "ws_exec", AsyncMock(return_value=(0, payload)))
    res = await devpod_tools._workspace_resources(None, {"workspace": "dev"}, "alice")
    assert res["mem_used"] == 536870912
    assert res["mem_limit"] == 1073741824
    assert res["disk_used"] == 2147483648
    assert res["disk_limit"] == 5368709120
    assert isinstance(res["cpu_pct"], float)


@pytest.mark.asyncio
async def test_workspace_resources_unlimited_mem(monkeypatch):
    from unittest.mock import AsyncMock
    payload = "1000000\n1000000\n100\nmax\n10 100\n"
    monkeypatch.setattr(devpod_tools, "ws_exec", AsyncMock(return_value=(0, payload)))
    res = await devpod_tools._workspace_resources(None, {"workspace": "dev"}, "alice")
    assert res["mem_limit"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/mcp/test_devpod_facades.py -k resources -v`
Expected: FAIL.

- [ ] **Step 3: Add registry definition**

```python
    "workspace_resources": {
        "description": "Retourne la consommation CPU / mémoire / disque du conteneur du workspace.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {"workspace": {"type": "string"}},
        },
        "scope": "read",
    },
```

- [ ] **Step 4: Write minimal implementation**

```python
def _to_int_or_none(token: str) -> int | None:
    token = token.strip()
    return int(token) if token.isdigit() else None


async def _workspace_resources(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    ws_id = f"{owner_login}-{name}"
    root = f"/workspaces/{name}"
    cg = "/sys/fs/cgroup"
    cmd = (
        f"cat {cg}/cpu.stat 2>/dev/null | awk '/usage_usec/{{print $2}}'; "
        f"sleep 0.1; "
        f"cat {cg}/cpu.stat 2>/dev/null | awk '/usage_usec/{{print $2}}'; "
        f"cat {cg}/memory.current 2>/dev/null || echo ''; "
        f"cat {cg}/memory.max 2>/dev/null || echo ''; "
        f"df -B1 --output=used,size {shlex.quote(root)} 2>/dev/null | tail -1"
    )
    rc, out = await ws_exec(owner_login, ws_id, cmd, timeout=10.0)
    if rc != 0:
        raise DevpodToolError(f"ressources indisponibles: {out}")
    lines = out.splitlines()
    u1 = _to_int_or_none(lines[0]) if len(lines) > 0 else None
    u2 = _to_int_or_none(lines[1]) if len(lines) > 1 else None
    cpu_pct = round((u2 - u1) / 100_000 * 100, 1) if u1 is not None and u2 is not None else 0.0
    mem_used = _to_int_or_none(lines[2]) if len(lines) > 2 else None
    mem_limit = _to_int_or_none(lines[3]) if len(lines) > 3 else None  # "max" -> None
    disk_used = disk_limit = None
    if len(lines) > 4:
        parts = lines[4].split()
        if len(parts) == 2:
            disk_used, disk_limit = _to_int_or_none(parts[0]), _to_int_or_none(parts[1])
    return {
        "cpu_pct": cpu_pct,
        "mem_used": mem_used,
        "mem_limit": mem_limit,
        "disk_used": disk_used,
        "disk_limit": disk_limit,
    }
```

Ajouter `"workspace_resources": _workspace_resources,` dans `_IMPLS`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/mcp/test_devpod_facades.py -k resources -v`
Expected: PASS.

- [ ] **Step 6: Lint + type + commit**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
git add backend/src/portal/mcp/devpod_tools/ backend/tests/mcp/test_devpod_facades.py
git commit -m "feat(mcp-devpod): workspace_resources — cgroup v2 + df via ws_exec (spec 25 §A)"
```

---

### Task A4: `session_interrupt`

**Files:** Modify `registry.py`, `__init__.py` ; Test `test_devpod_facades.py`

**Interfaces:**
- Consumes : `ws_exec`, `tmux` (existants).
- Produces : `_session_interrupt(conn, args, owner_login) -> {"interrupted": True}`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_session_interrupt_sends_ctrl_c(monkeypatch):
    from unittest.mock import AsyncMock
    fake = AsyncMock(return_value=(0, ""))
    monkeypatch.setattr(devpod_tools, "ws_exec", fake)
    res = await devpod_tools._session_interrupt(None, {"workspace": "dev", "session": "main"}, "alice")
    assert res == {"interrupted": True}
    sent_cmd = fake.await_args.args[2]
    assert "send-keys" in sent_cmd and "C-c" in sent_cmd
```

- [ ] **Step 2: Run** `uv run pytest tests/mcp/test_devpod_facades.py -k interrupt -v` → FAIL.

- [ ] **Step 3: Registry definition**

```python
    "session_interrupt": {
        "description": "Envoie un signal d'interruption (Ctrl-C) au process au premier plan d'une session.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {
                "workspace": {"type": "string"},
                "session": {"type": "string", "default": "main"},
            },
        },
        "scope": "exec",
    },
```

- [ ] **Step 4: Implementation**

```python
async def _session_interrupt(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    sess = str(args.get("session", "main"))
    rc, out = await ws_exec(
        owner_login, f"{owner_login}-{name}", tmux(f"send-keys -t {shlex.quote(sess)} C-c")
    )
    if rc != 0:
        raise DevpodToolError(out)
    return {"interrupted": True}
```

`_IMPLS` : `"session_interrupt": _session_interrupt,`.

- [ ] **Step 5: Run** `uv run pytest tests/mcp/test_devpod_facades.py -k interrupt -v` → PASS.

- [ ] **Step 6: Lint + type + commit**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
git add backend/src/portal/mcp/devpod_tools/ backend/tests/mcp/test_devpod_facades.py
git commit -m "feat(mcp-devpod): session_interrupt — Ctrl-C dans le pane (spec 25 §A)"
```

---

### Task A5: `session_close`

**Files:** Modify `registry.py`, `__init__.py` ; Test `test_devpod_facades.py`

**Interfaces:**
- Consumes : `ws_exec`, `tmux`.
- Produces : `_session_close(conn, args, owner_login) -> {"closed": True}`. `session` est **requis** (pas de défaut, on ne ferme jamais "main" par mégarde).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_session_close_kills_session(monkeypatch):
    from unittest.mock import AsyncMock
    fake = AsyncMock(return_value=(0, ""))
    monkeypatch.setattr(devpod_tools, "ws_exec", fake)
    res = await devpod_tools._session_close(None, {"workspace": "dev", "session": "build"}, "alice")
    assert res == {"closed": True}
    assert "kill-session" in fake.await_args.args[2]


@pytest.mark.asyncio
async def test_session_close_requires_session():
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._session_close(None, {"workspace": "dev"}, "alice")
```

- [ ] **Step 2: Run** `-k session_close` → FAIL.

- [ ] **Step 3: Registry definition**

```python
    "session_close": {
        "description": "Termine une session tmux nommée et le process qu'elle héberge.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace", "session"],
            "properties": {
                "workspace": {"type": "string"},
                "session": {"type": "string"},
            },
        },
        "scope": "exec",
    },
```

- [ ] **Step 4: Implementation**

```python
async def _session_close(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    sess = _require_str(args, "session")
    rc, out = await ws_exec(
        owner_login, f"{owner_login}-{name}", tmux(f"kill-session -t {shlex.quote(sess)}")
    )
    if rc != 0:
        raise DevpodToolError(out)
    return {"closed": True}
```

`_IMPLS` : `"session_close": _session_close,`.

- [ ] **Step 5: Run** `-k session_close` → PASS (2 tests).

- [ ] **Step 6: Lint + type + commit**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
git add backend/src/portal/mcp/devpod_tools/ backend/tests/mcp/test_devpod_facades.py
git commit -m "feat(mcp-devpod): session_close — kill-session tmux (spec 25 §A)"
```

---

### Task A6: `workspace_git_status`

**Files:** Modify `registry.py`, `__init__.py` ; Test `test_devpod_facades.py`

**Interfaces:**
- Consumes : `ws_exec`.
- Produces : `_workspace_git_status(conn, args, owner_login) -> {branch, staged, unstaged, untracked, diff?}`.

> Parse `git status --porcelain=v1 -b`. Première ligne `## branch...ahead` ⇒ branche. Colonnes XY : X (index/staged), Y (worktree/unstaged), `??` ⇒ untracked. `with_diff` ⇒ ajoute la sortie de `git diff`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_git_status_parses_porcelain(monkeypatch):
    from unittest.mock import AsyncMock
    out = "## dev...origin/dev\nM  staged.py\n M unstaged.py\n?? new.py\n"
    monkeypatch.setattr(devpod_tools, "ws_exec", AsyncMock(return_value=(0, out)))
    res = await devpod_tools._workspace_git_status(None, {"workspace": "dev"}, "alice")
    assert res["branch"] == "dev"
    assert res["staged"] == ["staged.py"]
    assert res["unstaged"] == ["unstaged.py"]
    assert res["untracked"] == ["new.py"]
    assert "diff" not in res


@pytest.mark.asyncio
async def test_git_status_with_diff(monkeypatch):
    from unittest.mock import AsyncMock
    calls = []
    async def fake(login, ws, cmd, timeout=30.0):
        calls.append(cmd)
        return (0, "## dev\n") if "status" in cmd else (0, "diff-body")
    monkeypatch.setattr(devpod_tools, "ws_exec", fake)
    res = await devpod_tools._workspace_git_status(None, {"workspace": "dev", "with_diff": True}, "alice")
    assert res["diff"] == "diff-body"
```

- [ ] **Step 2: Run** `-k git_status` → FAIL.

- [ ] **Step 3: Registry definition**

```python
    "workspace_git_status": {
        "description": "Retourne l'état git du workspace (branche, fichiers modifiés, diff optionnel).",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {
                "workspace": {"type": "string"},
                "with_diff": {"type": "boolean", "default": False},
            },
        },
        "scope": "read",
    },
```

- [ ] **Step 4: Implementation**

```python
def _parse_git_porcelain(out: str) -> dict[str, Any]:
    branch = ""
    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []
    for line in out.splitlines():
        if line.startswith("## "):
            branch = line[3:].split("...", 1)[0].strip()
            continue
        if len(line) < 3:
            continue
        x, y, path = line[0], line[1], line[3:]
        if line.startswith("??"):
            untracked.append(path)
            continue
        if x != " ":
            staged.append(path)
        if y != " ":
            unstaged.append(path)
    return {"branch": branch, "staged": staged, "unstaged": unstaged, "untracked": untracked}


async def _workspace_git_status(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    ws_id = f"{owner_login}-{name}"
    root = f"/workspaces/{name}"
    rc, out = await ws_exec(owner_login, ws_id, f"cd {shlex.quote(root)} && git status --porcelain=v1 -b")
    if rc != 0:
        raise DevpodToolError(f"git status impossible: {out}")
    result = _parse_git_porcelain(out)
    if bool(args.get("with_diff", False)):
        rc2, diff = await ws_exec(owner_login, ws_id, f"cd {shlex.quote(root)} && git diff")
        result["diff"] = diff if rc2 == 0 else ""
    return result
```

`_IMPLS` : `"workspace_git_status": _workspace_git_status,`.

- [ ] **Step 5: Run** `-k git_status` → PASS.

- [ ] **Step 6: Lint + type + commit**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
git add backend/src/portal/mcp/devpod_tools/ backend/tests/mcp/test_devpod_facades.py
git commit -m "feat(mcp-devpod): workspace_git_status — état + diff (spec 25 §A)"
```

---

### Task A7: `workspace_git_commit` (garde branche `dev`)

**Files:** Modify `registry.py`, `__init__.py` ; Test `test_devpod_facades.py`

**Interfaces:**
- Consumes : `ws_exec`.
- Produces : `_workspace_git_commit(conn, args, owner_login) -> {commit_sha, branch, pushed}`. **Refuse si la branche courante ≠ `dev`.**

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_git_commit_refuses_non_dev_branch(monkeypatch):
    async def fake(login, ws, cmd, timeout=30.0):
        return (0, "main\n")  # rev-parse --abbrev-ref HEAD
    monkeypatch.setattr(devpod_tools, "ws_exec", fake)
    with pytest.raises(devpod_tools.DevpodToolError, match="dev"):
        await devpod_tools._workspace_git_commit(None, {"workspace": "dev", "message": "feat: x"}, "alice")


@pytest.mark.asyncio
async def test_git_commit_on_dev_with_push(monkeypatch):
    seq = {"n": 0}
    async def fake(login, ws, cmd, timeout=30.0):
        seq["n"] += 1
        if "abbrev-ref" in cmd:
            return (0, "dev\n")
        if "rev-parse HEAD" in cmd:
            return (0, "abc123\n")
        return (0, "")
    monkeypatch.setattr(devpod_tools, "ws_exec", fake)
    res = await devpod_tools._workspace_git_commit(
        None, {"workspace": "dev", "message": "feat: x", "push": True}, "alice"
    )
    assert res == {"commit_sha": "abc123", "branch": "dev", "pushed": True}
```

- [ ] **Step 2: Run** `-k git_commit` → FAIL.

- [ ] **Step 3: Registry definition**

```python
    "workspace_git_commit": {
        "description": "Commit conventionnel sur la branche dev (garde de branche). Push optionnel.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace", "message"],
            "properties": {
                "workspace": {"type": "string"},
                "message": {"type": "string", "description": "Message commit conventionnel FR."},
                "files": {"type": "array", "items": {"type": "string"}},
                "push": {"type": "boolean", "default": False},
            },
        },
        "scope": "exec",
    },
```

- [ ] **Step 4: Implementation**

```python
async def _workspace_git_commit(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    message = _require_str(args, "message")
    ws_id = f"{owner_login}-{name}"
    root = f"/workspaces/{name}"

    rc, branch = await ws_exec(owner_login, ws_id, f"cd {shlex.quote(root)} && git rev-parse --abbrev-ref HEAD")
    branch = branch.strip()
    if rc != 0:
        raise DevpodToolError(f"branche introuvable: {branch}")
    if branch != "dev":
        raise DevpodToolError(f"commit refusé : branche '{branch}' ≠ 'dev'")

    files = args.get("files")
    if isinstance(files, list) and files:
        add = "git add " + " ".join(shlex.quote(str(f)) for f in files)
    else:
        add = "git add -A"
    rc, out = await ws_exec(
        owner_login, ws_id,
        f"cd {shlex.quote(root)} && {add} && git commit -m {shlex.quote(message)}",
    )
    if rc != 0:
        raise DevpodToolError(f"commit échoué: {out}")

    rc, sha = await ws_exec(owner_login, ws_id, f"cd {shlex.quote(root)} && git rev-parse HEAD")
    sha = sha.strip()

    pushed = False
    if bool(args.get("push", False)):
        rc, out = await ws_exec(owner_login, ws_id, f"cd {shlex.quote(root)} && git push origin dev")
        if rc != 0:
            raise DevpodToolError(f"push échoué: {out}")
        pushed = True
    return {"commit_sha": sha, "branch": branch, "pushed": pushed}
```

`_IMPLS` : `"workspace_git_commit": _workspace_git_commit,`.

- [ ] **Step 5: Run** `-k git_commit` → PASS (2 tests).

- [ ] **Step 6: Lint + type + commit**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
git add backend/src/portal/mcp/devpod_tools/ backend/tests/mcp/test_devpod_facades.py
git commit -m "feat(mcp-devpod): workspace_git_commit — commit gardé branche dev (spec 25 §A)"
```

---

### Task A8: `node_list`

**Files:** Modify `registry.py`, `__init__.py` ; Test `test_devpod_facades.py`

**Interfaces:**
- Consumes : `load_global()` (à importer depuis `...config.store`) → `cfg.hosts: list[HostConfig]`.
- Produces : `_node_list(conn, args, owner_login) -> list[dict]` : `[{node_id, name, host, status, capacity}]`.

> `status` = `"configured"` (aucune sonde live en v1) ; `capacity` = `None` (non suivi). On ne liste que les hosts à usage `workspaces`. Documenter ces deux champs comme statiques v1.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_node_list_maps_hosts(monkeypatch):
    h1 = SimpleNamespace(name="node1", address="10.0.0.1", docker_host="", usage="workspaces")
    h2 = SimpleNamespace(name="ci", address="", docker_host="tcp://x:2376", usage="tests")
    monkeypatch.setattr(devpod_tools, "load_global", lambda: SimpleNamespace(hosts=[h1, h2]))
    res = await devpod_tools._node_list(None, {}, "alice")
    assert res == [{"node_id": "node1", "name": "node1", "host": "10.0.0.1", "status": "configured", "capacity": None}]
```

- [ ] **Step 2: Run** `-k node_list` → FAIL.

- [ ] **Step 3: Registry definition**

```python
    "node_list": {
        "description": "Liste les nodes enrôlés et leur disponibilité.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
        "scope": "read",
    },
```

- [ ] **Step 4: Implementation**

Ajouter l'import `from ...config.store import load_global` (regrouper avec `_data_root`).

```python
async def _node_list(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    cfg = load_global()
    rows = []
    for h in cfg.hosts:
        if getattr(h, "usage", "workspaces") != "workspaces":
            continue
        rows.append({
            "node_id": h.name,
            "name": h.name,
            "host": h.address or h.docker_host or None,
            "status": "configured",
            "capacity": None,
        })
    return rows
```

`_IMPLS` : `"node_list": _node_list,`.

- [ ] **Step 5: Run** `-k node_list` → PASS.

- [ ] **Step 6: Full Lot A regression + lint + commit**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/ && uv run pytest tests/mcp/ -v
git add backend/src/portal/mcp/devpod_tools/ backend/tests/mcp/test_devpod_facades.py
git commit -m "feat(mcp-devpod): node_list — hosts enrôlés (spec 25 §A, lot A complet)"
```

---

# LOT B — Opérations asynchrones + create/delete/apply_recipe/profile_set

### Task B1: Store d'opérations (`operations.py`)

**Files:**
- Create: `backend/src/portal/mcp/devpod_tools/operations.py`
- Test: `backend/tests/mcp/test_devpod_operations.py`

**Interfaces:**
- Consumes : `_data_root()` depuis `...config.store`.
- Produces :
  - `create_operation(kind: str, workspace: str, owner_login: str) -> dict` (state `"pending"`, `operation_id` = uuid4 hex 32).
  - `get_operation(operation_id: str) -> dict | None`.
  - `list_operations(owner_login: str, workspace: str | None = None) -> list[dict]`.
  - `update_operation(operation_id: str, **fields: Any) -> dict`.
  - Forme d'un état : `{operation_id, kind, workspace, owner_login, state, progress, result, error, created_at, updated_at}`.

> `operation_id` validé par regex `^[0-9a-f]{32}$` (confinement chemin). Timestamps via `datetime.now(timezone.utc).isoformat()` (code applicatif — autorisé, contrairement aux scripts workflow). Écriture atomique tempfile + `os.replace`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/mcp/test_devpod_operations.py
import pytest
from portal.mcp.devpod_tools import operations


@pytest.fixture(autouse=True)
def _root(monkeypatch, tmp_path):
    monkeypatch.setattr(operations, "_data_root", lambda: tmp_path)


def test_create_then_get():
    op = operations.create_operation("workspace_create", "dev", "alice")
    assert op["state"] == "pending"
    assert op["kind"] == "workspace_create"
    assert op["workspace"] == "dev"
    assert op["owner_login"] == "alice"
    assert len(op["operation_id"]) == 32
    fetched = operations.get_operation(op["operation_id"])
    assert fetched == op


def test_update_operation():
    op = operations.create_operation("workspace_delete", "dev", "alice")
    upd = operations.update_operation(op["operation_id"], state="done", result={"deleted": True})
    assert upd["state"] == "done"
    assert upd["result"] == {"deleted": True}
    assert upd["updated_at"] >= op["created_at"]


def test_list_filters_by_owner_and_workspace():
    operations.create_operation("workspace_create", "dev", "alice")
    operations.create_operation("workspace_create", "proj", "alice")
    operations.create_operation("workspace_create", "dev", "bob")
    rows = operations.list_operations("alice")
    assert {r["workspace"] for r in rows} == {"dev", "proj"}
    rows_dev = operations.list_operations("alice", workspace="dev")
    assert [r["workspace"] for r in rows_dev] == ["dev"]


def test_get_unknown_returns_none():
    assert operations.get_operation("0" * 32) is None


def test_invalid_operation_id_rejected():
    with pytest.raises(operations.DevpodToolError):
        operations.get_operation("../etc/passwd")
```

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/mcp/test_devpod_operations.py -v` → FAIL (module absent).

- [ ] **Step 3: Write implementation**

```python
# backend/src/portal/mcp/devpod_tools/operations.py
"""Suivi des opérations asynchrones (spec 25 §B).

Un fichier YAML par opération sous /data/operations/. Écriture atomique
(tempfile + os.replace). Source de vérité = filesystem (pas de DB).
"""
from __future__ import annotations

import asyncio
import os
import re
import tempfile
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ...config.store import _data_root
from .errors import DevpodToolError

_OP_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_op_tasks: set[asyncio.Task[None]] = set()


def _operations_root() -> Path:
    root = _data_root() / "operations"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _op_path(operation_id: str) -> Path:
    if not _OP_ID_RE.fullmatch(operation_id):
        raise DevpodToolError(f"operation_id invalide: {operation_id!r}")
    return _operations_root() / f"{operation_id}.yaml"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_atomic(path: Path, data: dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def create_operation(kind: str, workspace: str, owner_login: str) -> dict[str, Any]:
    now = _now()
    op: dict[str, Any] = {
        "operation_id": uuid.uuid4().hex,
        "kind": kind,
        "workspace": workspace,
        "owner_login": owner_login,
        "state": "pending",
        "progress": 0,
        "result": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
    }
    _write_atomic(_op_path(op["operation_id"]), op)
    return op


def get_operation(operation_id: str) -> dict[str, Any] | None:
    path = _op_path(operation_id)
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def update_operation(operation_id: str, **fields: Any) -> dict[str, Any]:
    op = get_operation(operation_id)
    if op is None:
        raise DevpodToolError(f"opération inconnue: {operation_id}")
    op.update(fields)
    op["updated_at"] = _now()
    _write_atomic(_op_path(operation_id), op)
    return op


def list_operations(owner_login: str, workspace: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _operations_root().glob("*.yaml"):
        op = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not op or op.get("owner_login") != owner_login:
            continue
        if workspace is not None and op.get("workspace") != workspace:
            continue
        rows.append(op)
    rows.sort(key=lambda o: o.get("created_at", ""))
    return rows
```

- [ ] **Step 4: Run** `cd backend && uv run pytest tests/mcp/test_devpod_operations.py -v` → PASS (5 tests).

- [ ] **Step 5: Lint + type + commit**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
git add backend/src/portal/mcp/devpod_tools/operations.py backend/tests/mcp/test_devpod_operations.py
git commit -m "feat(mcp-devpod): store d'opérations async YAML atomique (spec 25 §B)"
```

---

### Task B2: Runner de fond (`run_operation_now` + `launch_operation`)

**Files:**
- Modify: `backend/src/portal/mcp/devpod_tools/operations.py`
- Test: `backend/tests/mcp/test_devpod_operations.py`

**Interfaces:**
- Produces :
  - `async def run_operation_now(operation_id: str, work: Callable[[], Awaitable[Any]]) -> None` — cœur testable : passe l'op à `running`, exécute `work`, écrit `done`+`result` ou `failed`+`error`.
  - `def launch_operation(kind: str, workspace: str, owner_login: str, work: Callable[[], Awaitable[Any]]) -> str` — crée l'op (pending), lance `run_operation_now` en tâche de fond, retourne `operation_id`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_run_operation_now_success():
    op = operations.create_operation("workspace_create", "dev", "alice")
    async def work():
        return {"workspace": "dev", "status": "running"}
    await operations.run_operation_now(op["operation_id"], work)
    final = operations.get_operation(op["operation_id"])
    assert final["state"] == "done"
    assert final["result"] == {"workspace": "dev", "status": "running"}
    assert final["progress"] == 100


@pytest.mark.asyncio
async def test_run_operation_now_failure():
    op = operations.create_operation("workspace_delete", "dev", "alice")
    async def work():
        raise ValueError("boom")
    await operations.run_operation_now(op["operation_id"], work)
    final = operations.get_operation(op["operation_id"])
    assert final["state"] == "failed"
    assert "boom" in final["error"]


@pytest.mark.asyncio
async def test_launch_operation_returns_id_and_runs():
    done = {}
    async def work():
        done["ran"] = True
        return {"ok": True}
    oid = operations.launch_operation("workspace_create", "dev", "alice", work)
    assert len(oid) == 32
    # laisse la task de fond s'exécuter
    for _ in range(50):
        if operations.get_operation(oid)["state"] == "done":
            break
        await asyncio.sleep(0.01)
    assert done.get("ran") is True
    assert operations.get_operation(oid)["result"] == {"ok": True}
```

Ajouter `import asyncio` en tête du fichier de test.

- [ ] **Step 2: Run** `-k operation_now or launch` → FAIL.

- [ ] **Step 3: Append implementation** (à la fin de `operations.py`)

```python
async def run_operation_now(operation_id: str, work: Callable[[], Awaitable[Any]]) -> None:
    update_operation(operation_id, state="running")
    try:
        result = await work()
        update_operation(operation_id, state="done", progress=100, result=result)
    except Exception as exc:
        update_operation(operation_id, state="failed", error=f"{type(exc).__name__}: {exc}")


def launch_operation(
    kind: str, workspace: str, owner_login: str, work: Callable[[], Awaitable[Any]]
) -> str:
    op = create_operation(kind, workspace, owner_login)
    oid = op["operation_id"]
    task = asyncio.create_task(run_operation_now(oid, work))
    _op_tasks.add(task)
    task.add_done_callback(_op_tasks.discard)
    return oid
```

- [ ] **Step 4: Run** `-k operation_now or launch` → PASS (3 tests).

- [ ] **Step 5: Lint + type + commit**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
git add backend/src/portal/mcp/devpod_tools/operations.py backend/tests/mcp/test_devpod_operations.py
git commit -m "feat(mcp-devpod): runner de fond d'opérations (run_operation_now + launch)"
```

---

### Task B3: Primitives `operations_get` / `operations_list`

**Files:** Modify `registry.py`, `__init__.py` ; Test `test_devpod_operations.py`

**Interfaces:**
- Consumes : `operations.get_operation`, `operations.list_operations`.
- Produces : `_operations_get`, `_operations_list` impls + entrées `_IMPLS`.

> `operations_get` ne renvoie une op que si `owner_login` correspond (isolation : un appelant ne voit pas les opérations d'un autre user).

- [ ] **Step 1: Write the failing test**

```python
from portal.mcp import devpod_tools


@pytest.mark.asyncio
async def test_operations_get_isolated_by_owner():
    op = operations.create_operation("workspace_create", "dev", "alice")
    res = await devpod_tools._operations_get(None, {"operation_id": op["operation_id"]}, "alice")
    assert res["state"] == "pending"
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._operations_get(None, {"operation_id": op["operation_id"]}, "bob")


@pytest.mark.asyncio
async def test_operations_list_for_owner():
    operations.create_operation("workspace_create", "dev", "alice")
    res = await devpod_tools._operations_list(None, {}, "alice")
    assert len(res) == 1
```

(Le fixture `_root` de ce fichier patche déjà `operations._data_root` ; `devpod_tools` importe les fonctions du même module `operations`, donc le patch s'applique.)

- [ ] **Step 2: Run** `-k operations_get or operations_list` → FAIL.

- [ ] **Step 3: Registry definitions**

```python
    "operations_get": {
        "description": "Retourne l'état, la progression et le résultat d'une opération asynchrone.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["operation_id"],
            "properties": {"operation_id": {"type": "string"}},
        },
        "scope": "read",
    },
    "operations_list": {
        "description": "Liste les opérations en cours, filtrables par workspace.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"workspace": {"type": "string"}},
        },
        "scope": "read",
    },
```

- [ ] **Step 4: Implementation**

Importer le module dans `__init__.py` : `from . import operations`.

```python
async def _operations_get(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    oid = _require_str(args, "operation_id")
    op = operations.get_operation(oid)
    if op is None or op.get("owner_login") != owner_login:
        raise DevpodToolError(f"opération inconnue: {oid}")
    return {k: op[k] for k in (
        "operation_id", "kind", "workspace", "state", "progress", "result", "error",
    )}


async def _operations_list(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    ws = args.get("workspace")
    rows = operations.list_operations(owner_login, workspace=ws if isinstance(ws, str) else None)
    return [
        {k: op[k] for k in ("operation_id", "kind", "workspace", "state", "progress")}
        for op in rows
    ]
```

`_IMPLS` : `"operations_get": _operations_get,` et `"operations_list": _operations_list,`.

- [ ] **Step 5: Run** `-k operations_get or operations_list` → PASS.

- [ ] **Step 6: Lint + type + commit**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
git add backend/src/portal/mcp/devpod_tools/ backend/tests/mcp/test_devpod_operations.py
git commit -m "feat(mcp-devpod): operations_get/list — suivi async, isolé par owner (spec 25 §B)"
```

---

### Task B4: Extraction `provision_workspace` + primitive `workspace_create`

**Files:**
- Create: `backend/src/portal/devpod/provision.py`
- Modify: `backend/src/portal/routes/workspace_ops.py` (déléguer la résolution+up)
- Modify: `registry.py`, `__init__.py`
- Test: `backend/tests/devpod/test_provision.py`, `backend/tests/mcp/test_devpod_async_lifecycle.py`

**Interfaces:**
- Produces :
  - `async def provision_workspace(login: str, params: ProvisionParams, conn: AsyncConnection) -> str` (retourne `ws_id`), où `ProvisionParams` est un pydantic/dataclass `{name, source, branch, git_credential, host, recipes: list[str], extra_sources, profile, recipe_volumes, generate_ssh_key, request_host}`.
  - `_workspace_create(conn, args, owner_login) -> {"operation_id": str}`.
- Consumes : registry de recettes, resolver secrets, `AsyncProfileRepository`, `DevPodService.up` (cf. `workspace_ops.workspace_up` lignes 236-359 — logique à déplacer).

> **Refactor DRY :** la logique de résolution recettes + secrets + profil + `svc.up` (actuellement inline dans `workspace_up`, `workspace_ops.py:236-359`) est déplacée dans `provision.provision_workspace`. La route `workspace_up` conserve ses préoccupations HTTP (validation 422, pre-flight git, sync spec DB) puis appelle `provision_workspace`. La primitive MCP `workspace_create` lance `provision_workspace` dans une opération de fond.

- [ ] **Step 1: Write the failing test (provision)**

```python
# backend/tests/devpod/test_provision.py
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from portal.devpod import provision


@pytest.mark.asyncio
async def test_provision_workspace_calls_up(monkeypatch):
    svc = SimpleNamespace(up=AsyncMock(return_value="alice-dev"))
    monkeypatch.setattr(provision, "_get_service", lambda: svc)
    monkeypatch.setattr(provision, "_resolve_recipes_and_secrets", AsyncMock(return_value=([], {})))
    monkeypatch.setattr(provision, "_load_profile", AsyncMock(return_value=None))
    params = provision.ProvisionParams(name="dev", source="git@x/y.git", recipes=[])
    ws_id = await provision.provision_workspace("alice", params, conn=None)
    assert ws_id == "alice-dev"
    svc.up.assert_awaited_once()
```

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/devpod/test_provision.py -v` → FAIL.

- [ ] **Step 3: Create `provision.py`**

Déplacer la logique de `workspace_up` (lignes 236-359 de `workspace_ops.py`) en fonctions internes. Structure :

```python
# backend/src/portal/devpod/provision.py
"""Orchestration de provisioning réutilisable (route REST + MCP workspace_create)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from ..config.models import WorkspaceSpec
from ..config.store import load_user
from ..profiles.models import Profile
from ..profiles.repository import AsyncProfileRepository, ProfileError
from ..recipes.models import RecipeMeta
from .service import DevPodService


def _get_service() -> DevPodService:
    from ..routes.workspace_ops import _get_service as _svc
    return _svc()


@dataclass
class ProvisionParams:
    name: str
    source: str
    branch: str = ""
    git_credential: str = ""
    host: str = ""
    recipes: list[str] = field(default_factory=list)
    extra_sources: list[Any] = field(default_factory=list)
    profile: Any = None
    recipe_volumes: list[str] = field(default_factory=list)
    generate_ssh_key: bool = False
    request_host: str = ""


async def _resolve_recipes_and_secrets(
    login: str, recipe_ids: list[str], conn: AsyncConnection
) -> tuple[list[RecipeMeta], dict[str, str]]:
    # Déplacé de workspace_ops.workspace_up (résolution recettes + _resolve_feature_secrets).
    from ..routes.workspace_ops import (
        _available_with_bundled_fallback, _get_recipe_registry, _resolve_feature_secrets,
    )
    from ..config.store import load_user as _lu
    from ..db.user_config import load_recipes_as_dict
    import asyncio
    if not recipe_ids:
        return [], {}
    reg = _get_recipe_registry()
    available = _available_with_bundled_fallback(await load_recipes_as_dict(login, conn))
    expanded = reg.expand_with_deps(recipe_ids, available)
    resolved = reg.resolve_order(expanded, available)
    refs = [ref for r in resolved for ref in r.requires_secrets]
    env: dict[str, str] = {}
    if refs:
        cfg = await _lu(login)
        env = await asyncio.to_thread(_resolve_feature_secrets, login, cfg.secret_ns, refs)
    return resolved, env


async def _load_profile(login: str, profile_ref: Any) -> Profile | None:
    if profile_ref is None:
        return None
    try:
        return await AsyncProfileRepository().get(profile_ref.scope, profile_ref.slug, login)
    except ProfileError:
        return None


async def provision_workspace(login: str, params: ProvisionParams, conn: AsyncConnection) -> str:
    resolved, feature_env = await _resolve_recipes_and_secrets(login, params.recipes, conn)
    profile_obj = await _load_profile(login, params.profile)
    ws = WorkspaceSpec(
        name=params.name, source=params.source, branch=params.branch,
        git_credential=params.git_credential, host=params.host, recipes=params.recipes,
        extra_sources=params.extra_sources, profile=params.profile,
        recipe_volumes=params.recipe_volumes,
    )
    return await _get_service().up(
        login=login, ws_spec=ws, recipes=resolved or None,
        feature_env=feature_env or None, generate_ssh_key=params.generate_ssh_key,
        request_host=params.request_host, profile=profile_obj,
    )
```

- [ ] **Step 4: Run** `cd backend && uv run pytest tests/devpod/test_provision.py -v` → PASS.

- [ ] **Step 5: Refactor route `workspace_up` to delegate**

Dans `workspace_ops.py`, remplacer le bloc lignes 236-359 (résolution recettes/secrets/profil + construction spec + `svc.up`) par un appel à `provision_workspace`, en conservant : validation des recipe IDs (220-234), pre-flight git (304-321), sync spec DB (323-346). Exemple du nouveau cœur :

```python
    from ..devpod.provision import ProvisionParams, provision_workspace
    try:
        ws_id = await provision_workspace(
            user.login,
            ProvisionParams(
                name=name, source=req.source, branch=req.branch,
                git_credential=req.git_credential, host=req.host, recipes=req.recipes,
                extra_sources=req.extra_sources, profile=req.profile,
                recipe_volumes=req.recipe_volumes, generate_ssh_key=req.generate_ssh_key,
                request_host=request.headers.get("x-forwarded-host") or request.url.hostname or "",
            ),
            conn,
        )
    except HostNotReadyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except UnknownHostError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, DependencyNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

- [ ] **Step 6: Run existing route tests** to confirm no regression.

Run: `cd backend && uv run pytest tests/ -k "workspace_up or workspace_ops" -v`
Expected: PASS (suite existante verte).

- [ ] **Step 7: Write the failing test (create primitive)**

```python
# backend/tests/mcp/test_devpod_async_lifecycle.py
from unittest.mock import AsyncMock
import pytest
from portal.mcp import devpod_tools


@pytest.mark.asyncio
async def test_workspace_create_launches_operation(monkeypatch):
    captured = {}
    def fake_launch(kind, workspace, owner_login, work):
        captured.update(kind=kind, workspace=workspace, owner=owner_login)
        return "f" * 32
    monkeypatch.setattr(devpod_tools.operations, "launch_operation", fake_launch)
    res = await devpod_tools._workspace_create(
        None, {"name": "dev", "repo": "git@x/y.git"}, "alice"
    )
    assert res == {"operation_id": "f" * 32}
    assert captured == {"kind": "workspace_create", "workspace": "dev", "owner": "alice"}


@pytest.mark.asyncio
async def test_workspace_create_requires_name_and_repo():
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._workspace_create(None, {"name": "dev"}, "alice")
```

- [ ] **Step 8: Run** `-k workspace_create` → FAIL.

- [ ] **Step 9: Registry + impl**

Registry :

```python
    "workspace_create": {
        "description": "Crée un workspace depuis un repo et une recette. Asynchrone : retourne un operation_id.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "repo"],
            "properties": {
                "name": {"type": "string"},
                "repo": {"type": "string", "description": "URL du dépôt git."},
                "branch": {"type": "string", "default": "dev"},
                "recipe": {"type": "string", "description": "Recette. Défaut : auto-détection."},
                "node": {"type": "string", "description": "Node cible. Défaut : placement auto."},
            },
        },
        "scope": "admin",
    },
```

Impl (dans `__init__.py`) — la création de connexion DB de fond suit le patron `DevPodService` (`async with _get_engine().begin()`) :

```python
async def _workspace_create(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    repo = _require_str(args, "repo")
    branch = str(args.get("branch", "dev"))
    recipe = args.get("recipe")
    node = str(args.get("node", ""))
    recipes = [str(recipe)] if isinstance(recipe, str) and recipe else []

    async def work() -> Any:
        from ...db.engine import _get_engine
        from ...devpod.provision import ProvisionParams, provision_workspace
        async with _get_engine().begin() as bg_conn:
            ws_id = await provision_workspace(
                owner_login,
                ProvisionParams(name=name, source=repo, branch=branch, host=node, recipes=recipes),
                bg_conn,
            )
        return {"workspace": name, "ws_id": ws_id, "status": "provisioning"}

    oid = operations.launch_operation("workspace_create", name, owner_login, work)
    return {"operation_id": oid}
```

`_IMPLS` : `"workspace_create": _workspace_create,`.

- [ ] **Step 10: Run** `-k workspace_create` → PASS (2 tests).

- [ ] **Step 11: Lint + type + commit**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/ && uv run pytest tests/ -q
git add backend/src/portal/devpod/provision.py backend/src/portal/routes/workspace_ops.py backend/src/portal/mcp/devpod_tools/ backend/tests/
git commit -m "feat(mcp-devpod): workspace_create async + extraction provision_workspace (spec 25 §B)"
```

---

### Task B5: `workspace_delete` (garde `confirm`, async)

**Files:** Modify `registry.py`, `__init__.py` ; Test `test_devpod_async_lifecycle.py`

**Interfaces:**
- Consumes : `operations.launch_operation`, `get_service().delete(login, ws_id, shelve=True)`.
- Produces : `_workspace_delete(conn, args, owner_login) -> {"operation_id"}`. Refuse si `confirm != True`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_workspace_delete_requires_confirm():
    with pytest.raises(devpod_tools.DevpodToolError, match="confirm"):
        await devpod_tools._workspace_delete(None, {"workspace": "dev", "confirm": False}, "alice")


@pytest.mark.asyncio
async def test_workspace_delete_launches_operation(monkeypatch):
    monkeypatch.setattr(devpod_tools.operations, "launch_operation",
                        lambda kind, ws, owner, work: "a" * 32)
    res = await devpod_tools._workspace_delete(None, {"workspace": "dev", "confirm": True}, "alice")
    assert res == {"operation_id": "a" * 32}
```

- [ ] **Step 2: Run** `-k workspace_delete` → FAIL.

- [ ] **Step 3: Registry definition**

```python
    "workspace_delete": {
        "description": "Supprime un workspace et son conteneur. Destructif.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace", "confirm"],
            "properties": {
                "workspace": {"type": "string"},
                "confirm": {"type": "boolean", "description": "Doit valoir true (garde anti-suppression)."},
            },
        },
        "scope": "admin",
    },
```

- [ ] **Step 4: Implementation**

```python
async def _workspace_delete(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    if args.get("confirm") is not True:
        raise DevpodToolError("suppression refusée : confirm doit valoir true")

    async def work() -> Any:
        result = await get_service().delete(owner_login, f"{owner_login}-{name}", shelve=True)
        return {"workspace": name, "deleted": True, **result}

    oid = operations.launch_operation("workspace_delete", name, owner_login, work)
    return {"operation_id": oid}
```

`_IMPLS` : `"workspace_delete": _workspace_delete,`.

- [ ] **Step 5: Run** `-k workspace_delete` → PASS (2 tests).

- [ ] **Step 6: Lint + type + commit**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
git add backend/src/portal/mcp/devpod_tools/ backend/tests/mcp/test_devpod_async_lifecycle.py
git commit -m "feat(mcp-devpod): workspace_delete async + garde confirm (spec 25 §B)"
```

---

### Task B6: `workspace_apply_recipe` (recréation async)

**Files:** Modify `registry.py`, `__init__.py` ; Test `test_devpod_async_lifecycle.py`

**Interfaces:**
- Consumes : `load_user`/`save_user` (config store), `get_service().delete(..., shelve=False)`, `provision.provision_workspace`.
- Produces : `_workspace_apply_recipe(conn, args, owner_login) -> {"operation_id"}`.

> Sémantique actée : update `spec.recipes` → persiste → `delete(shelve=False)` → `provision_workspace` avec la nouvelle recette. Opération de fond.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_apply_recipe_launches_operation(monkeypatch):
    captured = {}
    monkeypatch.setattr(devpod_tools.operations, "launch_operation",
                        lambda kind, ws, owner, work: captured.setdefault("kind", kind) or "b" * 32)
    res = await devpod_tools._workspace_apply_recipe(
        None, {"workspace": "dev", "recipe": "python"}, "alice"
    )
    assert res == {"operation_id": "b" * 32}
    assert captured["kind"] == "workspace_apply_recipe"


@pytest.mark.asyncio
async def test_apply_recipe_requires_recipe():
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._workspace_apply_recipe(None, {"workspace": "dev"}, "alice")
```

- [ ] **Step 2: Run** `-k apply_recipe` → FAIL.

- [ ] **Step 3: Registry definition**

```python
    "workspace_apply_recipe": {
        "description": "Applique/met à jour une recette (Dev Container Features) sur un workspace existant. Asynchrone (recréation).",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace", "recipe"],
            "properties": {
                "workspace": {"type": "string"},
                "recipe": {"type": "string"},
            },
        },
        "scope": "admin",
    },
```

- [ ] **Step 4: Implementation**

```python
async def _workspace_apply_recipe(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    recipe = _require_str(args, "recipe")

    async def work() -> Any:
        from ...config.store import load_user, save_user
        from ...db.engine import _get_engine
        from ...devpod.provision import ProvisionParams, provision_workspace
        cfg = await load_user(owner_login)
        spec = next((s for s in cfg.workspaces if s.name == name), None)
        if spec is None:
            raise DevpodToolError(f"workspace inconnu: {name}")
        recipes = list(dict.fromkeys([*spec.recipes, recipe]))
        spec_updated = spec.model_copy(update={"recipes": recipes})
        cfg.workspaces = [spec_updated if s.name == name else s for s in cfg.workspaces]
        await save_user(owner_login, cfg)
        await get_service().delete(owner_login, f"{owner_login}-{name}", shelve=False)
        async with _get_engine().begin() as bg_conn:
            ws_id = await provision_workspace(
                owner_login,
                ProvisionParams(
                    name=name, source=spec_updated.source, branch=spec_updated.branch,
                    git_credential=spec_updated.git_credential, host=spec_updated.host,
                    recipes=recipes, extra_sources=spec_updated.extra_sources,
                    profile=spec_updated.profile, recipe_volumes=spec_updated.recipe_volumes,
                ),
                bg_conn,
            )
        return {"workspace": name, "ws_id": ws_id, "recipes": recipes, "status": "provisioning"}

    oid = operations.launch_operation("workspace_apply_recipe", name, owner_login, work)
    return {"operation_id": oid}
```

`_IMPLS` : `"workspace_apply_recipe": _workspace_apply_recipe,`.

- [ ] **Step 5: Run** `-k apply_recipe` → PASS (2 tests).

- [ ] **Step 6: Lint + type + commit**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
git add backend/src/portal/mcp/devpod_tools/ backend/tests/mcp/test_devpod_async_lifecycle.py
git commit -m "feat(mcp-devpod): workspace_apply_recipe async par recréation (spec 25 §B)"
```

---

### Task B7: `workspace_profile_set` (recréation async)

**Files:** Modify `registry.py`, `__init__.py` ; Test `test_devpod_async_lifecycle.py`

**Interfaces:**
- Consumes : `load_user`/`save_user`, `ProfileRef`, `get_service().delete(..., shelve=False)`, `provision.provision_workspace`.
- Produces : `_workspace_profile_set(conn, args, owner_login) -> {"operation_id"}`.

> `profile` reçu = slug. On le pose en `ProfileRef(scope="user", slug=...)` sur le spec puis recréation. (Le scope `shared` éventuel est résolu par `AsyncProfileRepository.get` qui retombe sur shared ; en v1 on cible `user`.)

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_profile_set_launches_operation(monkeypatch):
    monkeypatch.setattr(devpod_tools.operations, "launch_operation",
                        lambda kind, ws, owner, work: "c" * 32)
    res = await devpod_tools._workspace_profile_set(
        None, {"workspace": "dev", "profile": "fullstack"}, "alice"
    )
    assert res == {"operation_id": "c" * 32}


@pytest.mark.asyncio
async def test_profile_set_requires_profile():
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._workspace_profile_set(None, {"workspace": "dev"}, "alice")
```

- [ ] **Step 2: Run** `-k profile_set` → FAIL.

- [ ] **Step 3: Registry definition**

```python
    "workspace_profile_set": {
        "description": "Applique un profil VS Code (extensions et réglages Open VSX) au workspace (recréation).",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace", "profile"],
            "properties": {
                "workspace": {"type": "string"},
                "profile": {"type": "string", "description": "Identifiant du profil VS Code."},
            },
        },
        "scope": "write",
    },
```

- [ ] **Step 4: Implementation**

```python
async def _workspace_profile_set(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    profile_slug = _require_str(args, "profile")

    async def work() -> Any:
        from ...config.models import ProfileRef
        from ...config.store import load_user, save_user
        from ...db.engine import _get_engine
        from ...devpod.provision import ProvisionParams, provision_workspace
        cfg = await load_user(owner_login)
        spec = next((s for s in cfg.workspaces if s.name == name), None)
        if spec is None:
            raise DevpodToolError(f"workspace inconnu: {name}")
        ref = ProfileRef(scope="user", slug=profile_slug)
        spec_updated = spec.model_copy(update={"profile": ref})
        cfg.workspaces = [spec_updated if s.name == name else s for s in cfg.workspaces]
        await save_user(owner_login, cfg)
        await get_service().delete(owner_login, f"{owner_login}-{name}", shelve=False)
        async with _get_engine().begin() as bg_conn:
            ws_id = await provision_workspace(
                owner_login,
                ProvisionParams(
                    name=name, source=spec_updated.source, branch=spec_updated.branch,
                    git_credential=spec_updated.git_credential, host=spec_updated.host,
                    recipes=spec_updated.recipes, extra_sources=spec_updated.extra_sources,
                    profile=ref, recipe_volumes=spec_updated.recipe_volumes,
                ),
                bg_conn,
            )
        return {"workspace": name, "ws_id": ws_id, "profile": profile_slug, "status": "provisioning"}

    oid = operations.launch_operation("workspace_profile_set", name, owner_login, work)
    return {"operation_id": oid}
```

`_IMPLS` : `"workspace_profile_set": _workspace_profile_set,`.

> Vérifier la signature exacte de `ProfileRef` (`config/models.py`) avant impl ; ajuster `scope`/`slug` si les noms de champs diffèrent.

- [ ] **Step 5: Run** `-k profile_set` → PASS (2 tests).

- [ ] **Step 6: Lint + type + full Lot B regression + commit**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/ && uv run pytest tests/mcp/ tests/devpod/ -q
git add backend/src/portal/mcp/devpod_tools/ backend/tests/mcp/test_devpod_async_lifecycle.py
git commit -m "feat(mcp-devpod): workspace_profile_set async par recréation (spec 25 §B, lot B complet)"
```

---

# LOT C — Harmonisation async lifecycle (spec 24) + secrets

### Task C1: Harmoniser `workspace_start` / `stop` / `restart` sur le modèle async

**Files:** Modify `__init__.py` ; Test : adapter `backend/tests/mcp/test_devpod_lifecycle.py` (existant).

**Interfaces:**
- `_workspace_start` / `_workspace_stop` / `_workspace_restart` retournent désormais `{"operation_id": str}` (au lieu de `{"workspace", "status"}`).
- Le travail réel est enveloppé dans `operations.launch_operation`.

> **Rétro-impact assumé (décision actée).** Les tests existants de `test_devpod_lifecycle.py` qui assertent `{"workspace": ..., "status": ...}` doivent être mis à jour pour asserter `{"operation_id": ...}` et vérifier l'effet via le `work` exécuté. C'est une rupture de contrat documentée dans la doc produit (Task D1).

- [ ] **Step 1: Update the existing tests (red)**

Remplacer dans `test_devpod_lifecycle.py` les assertions synchrones. Exemple pour `stop` :

```python
@pytest.mark.asyncio
async def test_stop_launches_operation(monkeypatch):
    svc = SimpleNamespace(stop=AsyncMock())
    monkeypatch.setattr(devpod_tools, "get_service", lambda: svc)
    captured = {}
    async def fake_launch(kind, ws, owner, work):
        captured["work"] = work
        return "d" * 32
    # launch_operation est sync ; on l'enveloppe pour exécuter work immédiatement dans le test
    def sync_launch(kind, ws, owner, work):
        import asyncio
        captured["kind"] = kind
        asyncio.get_event_loop().create_task(work())
        return "d" * 32
    monkeypatch.setattr(devpod_tools.operations, "launch_operation", sync_launch)
    res = await devpod_tools._workspace_stop(None, {"workspace": "dev"}, "alice")
    assert res == {"operation_id": "d" * 32}
    assert captured["kind"] == "workspace_stop"
```

(Pour `start` et `restart`, même forme ; vérifier `kind == "workspace_start"` / `"workspace_restart"`.)

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/mcp/test_devpod_lifecycle.py -v` → FAIL (impls encore synchrones).

- [ ] **Step 3: Rewrite the three impls**

```python
async def _workspace_stop(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)

    async def work() -> Any:
        await get_service().stop(owner_login, f"{owner_login}-{name}")
        return {"workspace": name, "status": "stopped"}

    return {"operation_id": operations.launch_operation("workspace_stop", name, owner_login, work)}


async def _workspace_start(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)

    async def work() -> Any:
        from ...db.engine import _get_engine
        async with _get_engine().begin() as bg_conn:
            await _start_existing(owner_login, name, bg_conn)
        return {"workspace": name, "status": "provisioning"}

    return {"operation_id": operations.launch_operation("workspace_start", name, owner_login, work)}


async def _workspace_restart(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)

    async def work() -> Any:
        from ...db.engine import _get_engine
        await get_service().stop(owner_login, f"{owner_login}-{name}")
        async with _get_engine().begin() as bg_conn:
            await _start_existing(owner_login, name, bg_conn)
        return {"workspace": name, "status": "provisioning"}

    return {"operation_id": operations.launch_operation("workspace_restart", name, owner_login, work)}
```

> Retirer l'ancienne gestion `ValueError` inline de `_workspace_start` : elle est désormais capturée par `run_operation_now` (→ état `failed`).

- [ ] **Step 4: Run** `cd backend && uv run pytest tests/mcp/test_devpod_lifecycle.py -v` → PASS.

- [ ] **Step 5: Lint + type + commit**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
git add backend/src/portal/mcp/devpod_tools/__init__.py backend/tests/mcp/test_devpod_lifecycle.py
git commit -m "refactor(mcp-devpod): start/stop/restart en modèle async operations_* (spec 25, harmonisation 24)"
```

---

### Task C2: `workspace_secrets_list`

**Files:** Modify `registry.py`, `__init__.py` ; Test `backend/tests/mcp/test_devpod_secrets.py`

**Interfaces:**
- Consumes : `load_user_db(owner_login, conn)` → `cfg.workspaces[].env: dict[str, str]`.
- Produces : `_workspace_secrets_list(conn, args, owner_login) -> {"references": [{target, reference}]}`. **Aucune valeur résolue.**

> Une "référence" = une valeur de `env` qui matche `^\$\{(vault|env)://...\}$`. Les `env` non-références (valeurs littérales) sont ignorées (ce ne sont pas des secrets).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/mcp/test_devpod_secrets.py
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from portal.mcp import devpod_tools


@pytest.mark.asyncio
async def test_secrets_list_only_references(monkeypatch):
    spec = SimpleNamespace(name="dev", env={
        "API_KEY": "${vault://bloc/api}",
        "DB_URL": "${env://DATABASE_URL}",
        "PLAIN": "literal",
    })
    cfg = SimpleNamespace(workspaces=[spec])
    monkeypatch.setattr(devpod_tools, "load_user_db", AsyncMock(return_value=cfg))
    res = await devpod_tools._workspace_secrets_list(None, {"workspace": "dev"}, "alice")
    refs = {r["target"]: r["reference"] for r in res["references"]}
    assert refs == {"API_KEY": "${vault://bloc/api}", "DB_URL": "${env://DATABASE_URL}"}
    assert "PLAIN" not in refs
```

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/mcp/test_devpod_secrets.py -k list -v` → FAIL.

- [ ] **Step 3: Registry definition**

```python
    "workspace_secrets_list": {
        "description": "Liste les références de secrets (${vault://...}) liées au workspace. Noms uniquement, jamais de valeurs.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace"],
            "properties": {"workspace": {"type": "string"}},
        },
        "scope": "read",
    },
```

- [ ] **Step 4: Implementation**

Ajouter une constante module (en tête de `__init__.py`, à côté de `_WS_NAME_RE`) :

```python
_SECRET_REF_RE = re.compile(r"^\$\{(vault|env)://.+\}$")
```

```python
async def _workspace_secrets_list(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    cfg = await load_user_db(owner_login, conn)
    spec = next((s for s in cfg.workspaces if s.name == name), None)
    if spec is None:
        raise DevpodToolError(f"workspace inconnu: {name}")
    refs = [
        {"target": key, "reference": val}
        for key, val in (spec.env or {}).items()
        if isinstance(val, str) and _SECRET_REF_RE.fullmatch(val)
    ]
    return {"references": refs}
```

`_IMPLS` : `"workspace_secrets_list": _workspace_secrets_list,`.

- [ ] **Step 5: Run** `-k list` → PASS.

- [ ] **Step 6: Lint + type + commit**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
git add backend/src/portal/mcp/devpod_tools/ backend/tests/mcp/test_devpod_secrets.py
git commit -m "feat(mcp-devpod): workspace_secrets_list — références sans valeurs (spec 25 §B)"
```

---

### Task C3: `workspace_secrets_bind`

**Files:** Modify `registry.py`, `__init__.py` ; Test `test_devpod_secrets.py`

**Interfaces:**
- Consumes : `load_user(owner_login)` + `save_user(owner_login, cfg)` (config store, écriture).
- Produces : `_workspace_secrets_bind(conn, args, owner_login) -> {"target", "bound": True}`. **Jamais la valeur résolue.**

> `bind` valide que `reference` matche le pattern `${vault://...}`/`${env://...}` (refus sinon), puis pose `spec.env[target] = reference`. `target` validé `^[A-Z_][A-Z0-9_]*$` (nom d'env var).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_secrets_bind_sets_reference(monkeypatch):
    spec = SimpleNamespace(name="dev", env={})
    def model_copy(update):
        spec.env = {**spec.env, **update.get("env", {})}
        return spec
    spec.model_copy = model_copy
    cfg = SimpleNamespace(workspaces=[spec])
    saved = {}
    monkeypatch.setattr(devpod_tools, "load_user", AsyncMock(return_value=cfg))
    monkeypatch.setattr(devpod_tools, "save_user", AsyncMock(side_effect=lambda l, c: saved.update(cfg=c)))
    res = await devpod_tools._workspace_secrets_bind(
        None, {"workspace": "dev", "reference": "${vault://b/n}", "target": "API_KEY"}, "alice"
    )
    assert res == {"target": "API_KEY", "bound": True}
    assert spec.env["API_KEY"] == "${vault://b/n}"


@pytest.mark.asyncio
async def test_secrets_bind_rejects_non_reference(monkeypatch):
    cfg = SimpleNamespace(workspaces=[SimpleNamespace(name="dev", env={})])
    monkeypatch.setattr(devpod_tools, "load_user", AsyncMock(return_value=cfg))
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._workspace_secrets_bind(
            None, {"workspace": "dev", "reference": "plaintext", "target": "API_KEY"}, "alice"
        )
```

- [ ] **Step 2: Run** `-k bind` → FAIL.

- [ ] **Step 3: Registry definition**

```python
    "workspace_secrets_bind": {
        "description": "Lie une référence ${vault://...} à une cible (env var) du workspace. Résolution interne au runtime ; aucune valeur retournée.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace", "reference", "target"],
            "properties": {
                "workspace": {"type": "string"},
                "reference": {"type": "string", "description": "Référence vault, ex. '${vault://bloc/nom}'."},
                "target": {"type": "string", "description": "Variable d'environnement cible."},
            },
        },
        "scope": "write",
    },
```

- [ ] **Step 4: Implementation**

Ajouter l'import `from ...config.store import load_user, save_user` (regrouper). Ajouter constante : `_ENV_TARGET_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")`.

```python
async def _workspace_secrets_bind(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    name = _require_ws(args)
    reference = _require_str(args, "reference")
    target = _require_str(args, "target")
    if not _SECRET_REF_RE.fullmatch(reference):
        raise DevpodToolError("reference invalide : attendu '${vault://...}' ou '${env://...}'")
    if not _ENV_TARGET_RE.fullmatch(target):
        raise DevpodToolError(f"cible env invalide: {target!r}")
    cfg = await load_user(owner_login)
    spec = next((s for s in cfg.workspaces if s.name == name), None)
    if spec is None:
        raise DevpodToolError(f"workspace inconnu: {name}")
    updated = spec.model_copy(update={"env": {**(spec.env or {}), target: reference}})
    cfg.workspaces = [updated if s.name == name else s for s in cfg.workspaces]
    await save_user(owner_login, cfg)
    return {"target": target, "bound": True}
```

`_IMPLS` : `"workspace_secrets_bind": _workspace_secrets_bind,`.

- [ ] **Step 5: Run** `-k bind` → PASS (2 tests).

- [ ] **Step 6: Lint + type + full regression + commit**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/ && uv run pytest tests/ -q
git add backend/src/portal/mcp/devpod_tools/ backend/tests/mcp/test_devpod_secrets.py
git commit -m "feat(mcp-devpod): workspace_secrets_bind — injection référence zéro-knowledge (spec 25 §B, lot C complet)"
```

---

# LOT D — Documentation produit

### Task D1: Régénérer la doc produit depuis le registre

**Files:** Modify : la doc produit générée (cf. commit `7a5f36b` "doc produit générée depuis le registre (§6)" — localiser le générateur et sa sortie).

**Interfaces:** N/A (génération).

> **Exigence du contrat principal :** toute primitive figée doit apparaître dans la doc produit, source de référence unique. Documenter aussi : (1) le modèle async `operations_*` ; (2) la rupture de contrat `start`/`stop`/`restart` (désormais `{operation_id}`) ; (3) l'écart `profile_set` (Section A spec → Lot B impl).

- [ ] **Step 1: Locate the doc generator**

Run: `cd backend && grep -rn "DEVPOD_PRIMITIVES" src/ docs/ scripts/ 2>/dev/null`
Identifier le script/test qui génère la doc §6 depuis `DEVPOD_PRIMITIVES`.

- [ ] **Step 2: Run the generator**

Exécuter le générateur identifié (probablement un script ou un test de génération). Vérifier que les 16 + nouvelles primitives apparaissent.

- [ ] **Step 3: Verify count**

Run: `cd backend && python -c "from portal.mcp.devpod_tools.registry import DEVPOD_PRIMITIVES; print(len(DEVPOD_PRIMITIVES)); print(sorted(DEVPOD_PRIMITIVES))"`
Expected : 16 (spec 24) + 14 nouvelles (`workspace_get`, `workspace_logs`, `workspace_resources`, `session_interrupt`, `session_close`, `workspace_git_status`, `workspace_git_commit`, `node_list`, `operations_get`, `operations_list`, `workspace_create`, `workspace_delete`, `workspace_apply_recipe`, `workspace_profile_set`, `workspace_secrets_list`, `workspace_secrets_bind`) = **32**.

> Note : 16 nouvelles primitives au total (8 Lot A + 2 operations + 4 create/delete/apply/profile + 2 secrets). Recompter à l'exécution ; ajuster.

- [ ] **Step 4: Commit**

```bash
git add <doc-générée>
git commit -m "docs(mcp-devpod): doc produit régénérée — primitives spec 25 + modèle async"
```

---

## Self-Review (effectuée)

**Spec coverage :**
- Section A : `workspace_get` (A1), `workspace_logs` (A2), `workspace_resources` (A3), `session_interrupt` (A4), `session_close` (A5), `workspace_git_status` (A6), `workspace_git_commit` (A7), `node_list` (A8), `workspace_profile_set` (B7 — écart documenté). ✓ 9/9.
- Section B : `operations_get`/`operations_list` (B3), `workspace_create` (B4), `workspace_delete` (B5), `workspace_apply_recipe` (B6), `workspace_secrets_list` (C2), `workspace_secrets_bind` (C3). ✓
- `agent_dispatch` : abandonné (décision actée) — pas de tâche. ✓
- Harmonisation async lifecycle 24 : C1. ✓
- Section C (HITL, re-placement, doc/rag) : hors périmètre — pas de tâche. ✓
- Doc produit (§6) : D1. ✓

**Placeholder scan :** aucun TODO/TBD ; tout step de code contient le code. Deux points d'auto-vérification explicites (signature `ProfileRef` en B7, localisation du générateur de doc en D1) — ce ne sont pas des placeholders mais des contrôles d'exactitude à l'exécution.

**Type consistency :** `_require_ws`/`_require_str`/`DevpodToolError`/`get_service`/`ws_exec`/`tmux`/`safe_workspace_path` réutilisés tels que définis spec 24. `operations.create_operation`/`get_operation`/`update_operation`/`list_operations`/`run_operation_now`/`launch_operation` cohérents entre B1/B2 et leurs consommateurs B3-C1. `ProvisionParams`/`provision_workspace` cohérents B4 → B6/B7. `_SECRET_REF_RE` partagé C2/C3.

---

## Execution Handoff

Plan complet et sauvegardé dans `docs/superpowers/plans/2026-06-27-mcp-devpod-complement.md`. Deux options d'exécution :

1. **Subagent-Driven (recommandé)** — un subagent frais par tâche, review entre les tâches, itération rapide.
2. **Inline Execution** — exécution dans cette session via executing-plans, par lots avec checkpoints.

Quelle approche ?
