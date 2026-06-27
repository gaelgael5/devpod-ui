# Plan — MCP `devpod` : pilotage des workspaces (spec 24)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans pour exécuter ce plan tâche par tâche. Les étapes utilisent des cases `- [ ]`.

**Goal :** exposer 16 primitives de pilotage des workspaces (`workspace_*`, `session_*`, `portal_*`) comme un backend MCP **interne** `devpod` dans la passerelle, avec autorisation par **scope** (read/write/exec/admin).

**Architecture :** la gateway route les appels via `handlers.execute_tool_call` → `aggregator.resolve_call` → `CallTarget(... transport ...)` → `open_session` (HTTP). On introduit `transport="internal"` : un backend dont les tools sont implémentés en Python dans le portail (façade I‑1 : le MCP appelle les services internes `DevPodService` + `ws_exec`, jamais SSH/tmux en direct). Le scope requis de chaque primitive vit dans sa `definition["scope"]` (contrat, spec §5) ; les scopes accordés vivent dans `mcp_apikey_grant.scopes` (nouvelle colonne) ; l'enforcement est deny‑by‑default dans `_resolve_target`.

**Tech Stack :** Python 3.12 + FastAPI + SQLAlchemy Core async + Postgres/Alembic + mcp SDK ; React/TS (UI scopes). Tests pytest ; `_ssh`/`DevPodService` mockés (skip Docker absent).

## Global Constraints
- `from __future__ import annotations` ; pydantic v2 `extra="forbid"` sur les modèles de config ; structlog, jamais `print`.
- async partout, jamais d'I/O bloquant dans un handler ; pas de `subprocess` direct hors façade `ws_exec` (qui encapsule `devpod ssh --stdio`).
- Confinement I‑5 : tout chemin workspace passe par `safe_workspace_path` (rejet `..`/absolu). Écriture I‑6 : tempfile + `mv` atomique.
- Agnosticisme (exigence §1) : aucune primitive ne dépend d'un agent ; le choix se fait dans `session_open.command`.
- Tout sur `dev`. Commits français conventionnels. Migrations : prochaine révision `029` (down `028`).
- Rétrocompat : un grant sans `scopes` (backends externes type deepwiki) → **aucun** enforcement de scope (comportement actuel inchangé).

## Décisions d'architecture (actées)
1. **transport="internal"** comme discriminant (champ DB déjà présent, inutilisé).
2. **Scope requis** dans `definition["scope"]` de chaque primitive (inerte côté client MCP, qui ne lit que name/description/inputSchema).
3. **Scopes accordés** dans `mcp_apikey_grant.scopes` (JSONB nullable). `null` = pas d'enforcement.
4. **Backend `devpod`** enregistré au lifespan pour l'owner admin (mono‑user actuel), `id="devpod"`, `namespace="devpod"`, `transport="internal"`, `url=""`.
5. **Isolation** : toutes les primitives filtrent par `owner_login` (le tenant de l'apikey/token).

---

## Lot 1 — Fondation : scopes + dispatch interne + bootstrap + `workspace_list`/`status`

**Files :**
- Create `backend/alembic/versions/029_grant_scopes.py`
- Modify `backend/src/portal/db/tables.py` (colonne `scopes` sur `mcp_apikey_grant`)
- Modify `backend/src/portal/db/mcp.py` (`set_grant`/`list_grants` : param + colonne `scopes`)
- Modify `backend/src/portal/mcp/aggregator.py` (enforcement scope dans `_resolve_target`)
- Modify `backend/src/portal/mcp/handlers.py` (dispatch interne sur `transport`)
- Create `backend/src/portal/mcp/devpod_tools/__init__.py` (registre + dispatch + impls)
- Create `backend/src/portal/mcp/devpod_tools/registry.py` (DEVPOD_PRIMITIVES : definition+scope)
- Create `backend/src/portal/mcp/devpod_bootstrap.py` (enregistrement backend + catalogue au lifespan)
- Modify `backend/src/portal/app.py` (appel bootstrap dans le lifespan, après migrations)
- Tests : `backend/tests/mcp/test_scope_enforcement.py`, `backend/tests/mcp/test_devpod_dispatch.py`, `backend/tests/mcp/test_devpod_workspace_read.py`

### Migration 029 (suivre le pattern 028)
```python
def upgrade() -> None:
    op.add_column("mcp_apikey_grant", sa.Column("scopes", JSONB(), nullable=True))
def downgrade() -> None:
    op.drop_column("mcp_apikey_grant", "scopes")
```
`tables.py` : ajouter `Column("scopes", JSONB, nullable=True)` à `mcp_apikey_grant` (null = pas d'enforcement).

### `db/mcp.py`
- `set_grant(..., scopes: list[str] | None = None)` → `.values(..., scopes=scopes)` + `on_conflict_do_update` set `scopes`.
- `list_grants` : ajouter `mcp_apikey_grant.c.scopes` aux colonnes sélectionnées.

### Enforcement — `aggregator._resolve_target` (après le `match`, avant le `return CallTarget`)
```python
required_scope = (match["definition"] or {}).get("scope")
grant_scopes = grant.get("scopes")
if required_scope and grant_scopes is not None and required_scope not in grant_scopes:
    return None  # scope non accordé → deny-by-default (audité "denied")
```
- **TDD** : `test_scope_enforcement.py` — grant `scopes=["read"]` + primitive `scope="admin"` → `resolve_call` renvoie `None` ; `scope="read"` → `CallTarget`. Grant `scopes=None` + primitive `scope="admin"` → autorisé (rétrocompat). Backend externe (definition sans `scope`) → autorisé.

### Dispatch interne — `handlers.execute_tool_call` (remplacer le bloc `async with session_fn(...)`)
```python
from portal.mcp.devpod_tools import execute_internal_tool  # en tête

started = time.perf_counter()
try:
    if target.transport == "internal":
        result = await execute_internal_tool(
            conn, target.original_name, arguments, owner_login=owner_login
        )
    else:
        async with session_fn(target.url, bearer=bearer) as session:
            result = await call_backend_tool(session, target.original_name, arguments)
except BackendUnavailable as exc:
    ...  # inchangé
```
> Note : `resolve_bearer` reste appelé avant (no-op pour un backend interne : pas de `backend_key_id`).
- **TDD** : `test_devpod_dispatch.py` — un backend stub `transport="internal"` + une primitive bidon ; `execute_tool_call` route vers `execute_internal_tool` (monkeypatch) et n'ouvre **pas** de session HTTP.

### Registre — `devpod_tools/registry.py`
Un dict `DEVPOD_PRIMITIVES: dict[str, dict]` : pour chaque primitive, la `definition` au format MCP **avec** la clé `scope`. Copier les schémas exacts de la spec §5. Exemple :
```python
DEVPOD_PRIMITIVES = {
  "workspace_list": {
    "description": "Liste les workspaces avec leur statut, node et recette.",
    "inputSchema": {"type":"object","additionalProperties":False,
      "properties":{"status":{"type":"string","enum":["running","stopped","all"],"default":"all"}}},
    "scope": "read",
  },
  "workspace_status": {
    "description": "Retourne l'état de santé d'un workspace : conteneur et agent.",
    "inputSchema": {"type":"object","additionalProperties":False,"required":["workspace"],
      "properties":{"workspace":{"type":"string"}}},
    "scope": "read",
  },
  # … les 14 autres (lots 2‑6), chacune avec son scope.
}
```
`definition_hash(defn) -> str` = sha256 du JSON canonique (`json.dumps(defn, sort_keys=True)`).

### Dispatch + impls — `devpod_tools/__init__.py`
```python
async def execute_internal_tool(conn, name, arguments, *, owner_login) -> types.CallToolResult:
    impl = _IMPLS.get(name)
    if impl is None:
        raise McpError(ErrorData(code=METHOD_NOT_FOUND, message="unknown devpod tool"))
    try:
        payload = await impl(conn, arguments, owner_login)
    except DevpodToolError as exc:           # erreur métier → isError (pas 500)
        return _err(exc.message)
    return _ok(payload)

def _ok(payload) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(payload))])
def _err(msg) -> types.CallToolResult:
    return types.CallToolResult(isError=True, content=[types.TextContent(type="text", text=msg)])
```
`_IMPLS: dict[str, Callable]` peuplé lot par lot. `DevpodToolError(message)` = exception métier (workspace introuvable, chemin invalide…).

**workspace_list impl :**
```python
async def _workspace_list(conn, args, owner_login):
    wss = await get_service().list_workspaces(owner_login)
    status = args.get("status", "all")
    rows = [_ws_summary(w) for w in wss
            if status == "all" or w.get("status") == status]
    return rows  # [{id,name,repo,status,node,recipe,tags}]
```
**workspace_status impl :**
```python
async def _workspace_status(conn, args, owner_login):
    name = _require_ws(args)                      # valide nom (regex)
    ws_id = f"{owner_login}-{name}"
    st = await get_service().status(owner_login, ws_id)
    return {"workspace": name, "health": st.get("status","unknown"),
            "container_up": st.get("status") == "running", "agent_up": None}
```
`_require_ws(args)` valide via la regex de `_validate_ws_name`. `get_service()` = accès au singleton `DevPodService` (cf. `routes/workspace_ops.py:_get_service`).

### Bootstrap — `devpod_bootstrap.py`
```python
DEVPOD_BACKEND_ID = "devpod"
async def bootstrap_devpod(conn, admin_login: str) -> None:
    if await get_backend(conn, admin_login, DEVPOD_BACKEND_ID) is None:
        await insert_backend(conn, id=DEVPOD_BACKEND_ID, owner_login=admin_login,
            namespace="devpod", name="DevPod workspaces", url="", transport="internal")
    present = []
    for original_name, defn in DEVPOD_PRIMITIVES.items():
        await upsert_primitive(conn, backend_id=DEVPOD_BACKEND_ID, kind="tool",
            original_name=original_name, definition=defn, definition_hash=definition_hash(defn))
        present.append(original_name)
    await prune_absent(conn, DEVPOD_BACKEND_ID, "tool", present)
```
`app.py` lifespan : après `run_migrations`, dans une transaction, appeler `bootstrap_devpod(conn, settings.admin_login)` (admin_login = le login admin de la config ; à confirmer : `load_global().auth` ou un réglage existant — sinon premier user `admin`).

- **TDD** `test_devpod_workspace_read.py` : monkeypatch `DevPodService.list_workspaces`/`status` ; `_workspace_list` filtre par statut ; `_workspace_status` mappe `running`→`container_up=True` ; nom invalide → `DevpodToolError`.

**Commit** : `feat(mcp-devpod): lot 1 — backend interne, scopes, bootstrap, workspace_list/status`.

---

## Lot 2 — Lecture fichiers : confinement + `workspace_tree` / `workspace_read_file`

**Files :**
- Create `backend/src/portal/devpod/exec.py` (extraction de `_ssh` → `ws_exec`, + helpers tmux)
- Modify `backend/src/portal/routes/workspace_sessions.py` (importer `ws_exec` au lieu du `_ssh` local)
- Create `backend/src/portal/mcp/devpod_tools/paths.py` (`safe_workspace_path`)
- Modify `backend/src/portal/mcp/devpod_tools/__init__.py` (impls + registry tree/read_file)
- Tests : `backend/tests/devpod/test_ws_exec.py`, `backend/tests/mcp/test_devpod_paths.py`, `backend/tests/mcp/test_devpod_files.py`

### `devpod/exec.py` (refactor DRY, façade I‑1)
Déplacer la fonction `_ssh` de `workspace_sessions.py` telle quelle, renommée `ws_exec(login, ws_id, command, timeout=30.0) -> tuple[int, str]`, + les helpers tmux (`_tmux`, `_TMUX_SOCK_DETECT`, `locate_start_sh`). `workspace_sessions.py` ré‑importe depuis `exec.py` (comportement identique, tests existants verts).

### `paths.py`
```python
import posixpath
def safe_workspace_path(workspace: str, path: str) -> str:
    if path.startswith("/") or "\0" in path:
        raise DevpodToolError("chemin absolu interdit")
    root = f"/workspaces/{workspace}"
    resolved = posixpath.normpath(posixpath.join(root, path or "."))
    if resolved != root and not resolved.startswith(root + "/"):
        raise DevpodToolError("chemin hors du workspace")
    return resolved
```
- **TDD** `test_devpod_paths.py` : `.`→root ; `src/a.py`→`/workspaces/w/src/a.py` ; `../x`→erreur ; `/etc/passwd`→erreur ; `a/../../b`→erreur.

### Impls (via `ws_exec`)
```python
async def _workspace_read_file(conn, args, owner_login):
    name = _require_ws(args); p = safe_workspace_path(name, args["path"])
    ws_id = f"{owner_login}-{name}"
    rc, out = await ws_exec(owner_login, ws_id, f"cat {shlex.quote(p)}")
    if rc != 0: raise DevpodToolError(f"lecture impossible: {out}")
    return {"path": args["path"], "content": out, "size": len(out.encode()),
            "sha256": hashlib.sha256(out.encode()).hexdigest()}

async def _workspace_tree(conn, args, owner_login):
    name = _require_ws(args); p = safe_workspace_path(name, args.get("path","."))
    depth = args.get("depth", 2); ignore = args.get("ignore", [".git",".venv","node_modules","__pycache__"])
    prune = " ".join(f"-name {shlex.quote(i)} -prune -o" for i in ignore)
    cmd = f"cd {shlex.quote(p)} && find . -maxdepth {int(depth)} {prune} -print"
    rc, out = await ws_exec(owner_login, f"{owner_login}-{name}", cmd)
    if rc != 0: raise DevpodToolError(out)
    return _build_tree(out.splitlines())   # → {name,type,children[]}
```
Registry tree/read_file : schémas exacts spec §5 + `scope:"read"`.
- **TDD** `test_devpod_files.py` : monkeypatch `ws_exec` ; read_file renvoie content+sha256 ; chemin `..` → `DevpodToolError` avant tout appel ; tree parse une sortie `find` mockée en arbre imbriqué.

**Commit** : `feat(mcp-devpod): lot 2 — confinement chemins + workspace_tree/read_file (ws_exec extrait)`.

---

## Lot 3 — Écriture / exécution : `workspace_mkdir` / `workspace_write_file` / `workspace_exec`

**Files :** Modify `devpod_tools/__init__.py` + `registry.py` ; Test `backend/tests/mcp/test_devpod_write.py`.

```python
async def _workspace_mkdir(conn, args, owner_login):
    name = _require_ws(args); p = safe_workspace_path(name, args["path"])
    rc, out = await ws_exec(owner_login, f"{owner_login}-{name}", f"mkdir -p {shlex.quote(p)}")
    if rc != 0: raise DevpodToolError(out)
    return {"path": args["path"]}

async def _workspace_write_file(conn, args, owner_login):       # atomique I‑6
    name = _require_ws(args); p = safe_workspace_path(name, args["path"])
    content = args["content"]; create = args.get("create_dirs", True)
    b64 = base64.b64encode(content.encode()).decode()
    parent = posixpath.dirname(p)
    mk = f"mkdir -p {shlex.quote(parent)} && " if create else ""
    cmd = (f'{mk}tmp=$(mktemp {shlex.quote(parent)}/.tmp.XXXXXX) && '
           f'echo {b64} | base64 -d > "$tmp" && mv -f "$tmp" {shlex.quote(p)}')
    rc, out = await ws_exec(owner_login, f"{owner_login}-{name}", cmd)
    if rc != 0: raise DevpodToolError(out)
    return {"path": args["path"], "sha256": hashlib.sha256(content.encode()).hexdigest(),
            "bytes": len(content.encode())}

async def _workspace_exec(conn, args, owner_login):
    name = _require_ws(args); cmd = args["command"]; t = args.get("timeout_s", 60)
    cwd = safe_workspace_path(name, args["cwd"]) if args.get("cwd") else f"/workspaces/{name}"
    full = f"cd {shlex.quote(cwd)} && {cmd}"
    rc, out = await ws_exec(owner_login, f"{owner_login}-{name}", full, timeout=float(t))
    return {"stdout": out, "stderr": "", "exit_code": rc}   # ws_exec fusionne stdout+stderr (cf. §backlog: séparation)
```
Registry : mkdir/write_file `scope:"write"` ; exec `scope:"exec"`. Schémas exacts spec §5.
- **TDD** `test_devpod_write.py` : write_file appelle `ws_exec` avec un `mv` (atomique) et renvoie sha256/bytes corrects ; `create_dirs=false` n'émet pas de `mkdir` parent ; chemin invalide → `DevpodToolError` sans appel.
> Note d'implémentation à valider au lot : `ws_exec` fusionne stdout+stderr → `workspace_exec.stderr` est vide en v1 (limitation à documenter §6 ; séparation = backlog).

**Commit** : `feat(mcp-devpod): lot 3 — workspace_mkdir/write_file (atomique)/exec`.

---

## Lot 4 — Cycle de vie : `workspace_start` / `workspace_stop` / `workspace_restart` (scope admin)

**Files :** Modify `devpod_tools/__init__.py` + `registry.py` ; Test `test_devpod_lifecycle.py`.
**Incertitude à lever en début de lot** : `DevPodService.up` exige un `WorkspaceSpec` complet. Pour (re)démarrer un workspace **existant**, recharger son spec depuis la config user (`routes/workspace_ops.py` création/`workspaces.yaml`). Lire ce chemin d'abord ; factoriser un helper `reload_ws_spec(login, name) -> WorkspaceSpec` réutilisé par le router et le MCP.

```python
async def _workspace_stop(conn, args, owner_login):
    name = _require_ws(args); await get_service().stop(owner_login, f"{owner_login}-{name}")
    return {"workspace": name, "status": "stopped"}

async def _workspace_start(conn, args, owner_login):
    name = _require_ws(args); spec = await reload_ws_spec(owner_login, name)
    await get_service().up(owner_login, spec)
    return {"workspace": name, "status": "provisioning"}

async def _workspace_restart(conn, args, owner_login):
    await _workspace_stop(conn, args, owner_login)
    return await _workspace_start(conn, args, owner_login)
```
Registry : les trois `scope:"admin"`. Schéma identique (`required:["workspace"]`).
- **TDD** : monkeypatch `DevPodService.stop/up` + `reload_ws_spec` ; stop→`{status:"stopped"}` ; start→up appelé avec le spec rechargé ; restart→stop puis up.

**Commit** : `feat(mcp-devpod): lot 4 — workspace_start/stop/restart`.

---

## Lot 5 — Sessions tmux : `session_open` / `send` / `capture` / `list` / `get`

**Files :** Modify `devpod_tools/__init__.py` + `registry.py` ; réutiliser les helpers tmux de `devpod/exec.py` ; Test `test_devpod_sessions.py`.

```python
async def _session_open(conn, args, owner_login):     # idempotent (I‑3)
    name=_require_ws(args); sess=args.get("name","main"); command=args["command"]
    cwd = safe_workspace_path(name, args["cwd"]) if args.get("cwd") else f"/workspaces/{name}"
    inner = f"cd {shlex.quote(cwd)} && {command}"
    cmd = (f"{_TMUX} has-session -t {shlex.quote(sess)} 2>/dev/null || "
           f"{_TMUX} new-session -d -s {shlex.quote(sess)} {shlex.quote(inner)}")
    rc,out = await ws_exec(owner_login, f"{owner_login}-{name}", cmd)
    if rc!=0: raise DevpodToolError(out)
    return {"session_id": f"{name}:{sess}", "workspace": name, "name": sess, "command": command}

async def _session_send(conn, args, owner_login):
    name=_require_ws(args); sess=args.get("session","main"); text=args["text"]
    submit = args.get("submit", True)
    keys = f"{shlex.quote(text)}" + (" Enter" if submit else "")
    rc,out = await ws_exec(owner_login, f"{owner_login}-{name}",
        f"{_TMUX} send-keys -t {shlex.quote(sess)} {keys}")
    if rc!=0: raise DevpodToolError(out)
    return {"sent": True}

async def _session_capture(conn, args, owner_login):        # buffer brut, ANSI (I‑2/I‑4)
    name=_require_ws(args); sess=args.get("session","main"); lines=args.get("lines",200)
    rc,out = await ws_exec(owner_login, f"{owner_login}-{name}",
        f"{_TMUX} capture-pane -p -e -t {shlex.quote(sess)} -S -{int(lines)}")
    if rc!=0: raise DevpodToolError(out)
    return {"output": out}

async def _session_list(conn, args, owner_login):
    name=_require_ws(args)
    rc,out = await ws_exec(owner_login, f"{owner_login}-{name}",
        f"{_TMUX} list-sessions -F '#{{session_name}}|#{{pane_current_command}}' 2>/dev/null || true")
    return [_parse_session(line, name) for line in out.splitlines() if line]

async def _session_get(conn, args, owner_login):            # métadonnées ≠ buffer (I‑4)
    name=_require_ws(args); sess=args.get("session","main")
    rc,out = await ws_exec(owner_login, f"{owner_login}-{name}",
        f"{_TMUX} display-message -p -t {shlex.quote(sess)} "
        f"'#{{session_name}}|#{{pane_id}}|#{{pane_current_command}}|#{{session_created}}' 2>/dev/null || true")
    if not out.strip(): raise DevpodToolError("session introuvable")
    return _parse_session_meta(out, name)
```
`_TMUX` = la commande tmux préfixée socket (`_TMUX_SOCK_DETECT` de `exec.py`). `_origin`/`_depth` de `session_send` : présents au schéma, **non câblés** (I‑7) — ignorés. Registry : `session_open/send` `scope:"exec"` ; `capture/list/get` `scope:"read"`. Schémas exacts spec §5.
- **TDD** `test_devpod_sessions.py` : monkeypatch `ws_exec` ; open émet `has-session || new-session` (idempotent) ; send avec `submit=false` n'ajoute pas `Enter` ; capture passe `-e` (ANSI) ; list parse plusieurs sessions ; get distinct de capture (métadonnées).

**Commit** : `feat(mcp-devpod): lot 5 — session_open/send/capture/list/get`.

---

## Lot 6 — `portal_reload` + UI scopes + documentation produit (§6)

**Files :**
- Modify `devpod_tools/__init__.py` + `registry.py` (`portal_reload`, `scope:"admin"`) :
  ```python
  async def _portal_reload(conn, args, owner_login):
      name=_require_ws(args)
      await get_service().reload(owner_login, f"{owner_login}-{name}")  # modèle (a) : reconnexion forcée
      return {"workspace": name, "reconnected": True}
  ```
  Vérifier l'existence d'un point de reconnexion dans `DevPodService` (port‑forward/exposure) ; sinon factoriser depuis la logique de reconcile existante.
- **UI scopes** :
  - Modify `frontend/src/features/mcp/api.ts` (type `MCPGrant`/`GrantSetBody` : champ `scopes: string[] | null`)
  - Modify `frontend/src/features/mcp/MCPApikeys.tsx` (`GrantEditor` : multi‑sélection des scopes quand le backend est `devpod`)
  - Modify `frontend/src/features/oauth/ConsentPage.tsx` (choix des scopes pour un grant devpod)
  - Modify `backend/src/portal/routes/mcp.py` + `schemas` (DTO grant accepte `scopes`)
- **Doc produit (§6)** : Create `docs/mcp/devpod-tools.md` généré depuis `DEVPOD_PRIMITIVES` (nom fédéré `devpod__*`, description, inputSchema, retour, scope) — script `scripts/gen_mcp_docs.py` qui sérialise le registre, pour garantir doc ≡ contrat.
- Tests : `test_devpod_portal.py` (reload) ; `MCPApikeys.test.tsx` (sélection scopes) ; test du générateur de doc (snapshot du registre).

**Commit** : `feat(mcp-devpod): lot 6 — portal_reload, UI scopes, doc produit`.

---

## Self-review (couverture spec)
- **§3 invariants** : I‑1 façade (`ws_exec`/`DevPodService`, jamais SSH direct) ✓ ; I‑2 capture brute `-e` ✓ ; I‑3 `session` explicite + idempotence ✓ ; I‑4 get≠capture (impls distinctes) ✓ ; I‑5 `safe_workspace_path` (lot 2, appliqué tree/read/mkdir/write) ✓ ; I‑6 tempfile+mv (lot 3) ✓ ; I‑7 `_origin`/`_depth` au schéma non câblés ✓.
- **§4 scopes** : read/write/exec/admin par primitive + enforcement `_resolve_target` (lot 1) ✓.
- **§5 primitives** : 16/16 couvertes (lots 1‑6), schémas exacts copiés de la spec.
- **§6 doc** : générateur depuis le registre (lot 6) ✓.
- **§7 backlog** : `expected_sha256`, `link_state`, récursion, stderr séparé, VM directe — explicitement hors v1.
- **Zones à lever en début de lot** : (a) `admin_login` pour le bootstrap (lot 1) ; (b) `reload_ws_spec` pour start/restart (lot 4) ; (c) point de reconnexion `reload` (lot 6). Chacune = première étape de son lot (lecture ciblée avant code).
