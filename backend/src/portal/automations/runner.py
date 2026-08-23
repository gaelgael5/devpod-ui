"""Runner d'automates : consomme le journal `app_event` par curseur et appelle.

Pour chaque event (ordre `seq`), les automates actifs sont évalués dans l'ordre
d'évaluation (`position`) :

- **matching** : `event_type` déclencheur ET portée (`*` ou workspace de l'event) ;
- **debounce** (`delay_minutes`, fenêtre glissante) : un event trop jeune fait
  « caler » l'automate — son curseur n'avance pas au-delà, il réessaiera plus tard
  quand l'event aura décanté (les modifs rapprochées d'une même version, dédupées
  par `dedup_key`, se replient sur un seul appel) ;
- **stop_chain** : un automate qui matche et dont l'appel réussit **consomme**
  l'event → les automates de priorité inférieure sont bloqués (run `skipped`) ;
- **anti-rejeu** : `claim` (index unique partiel) garantit un appel par version ;
- **anti-SSRF** : l'URL cible passe par `pinned_request` (résolution + épinglage) ;
- **secrets** : les en-têtes `secret_ref` sont résolus au vault à l'exécution,
  jamais journalisés (l'aperçu de requête ne contient ni en-têtes ni secrets).
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog

from ..db import app_event as je
from ..db import automation as adb
from ..db import automation_run as ar
from ..db.engine import _get_engine
from ..routes._ssrf import pinned_request

_log = structlog.get_logger(__name__)

_BATCH = 200
_RESP_PREVIEW_MAX = 2000
_DEFAULT_INTERVAL_S = 10.0
_VAR_RE = re.compile(r"\{([a-zA-Z0-9_.]+)\}")


def matches(automation: dict[str, Any], event: dict[str, Any]) -> bool:
    """L'automate est-il déclenché par cet event ? (uniquement sur le type d'event)."""
    return event["event_type"] in (automation.get("event_types") or [])


def dedup_key(event: dict[str, Any]) -> str:
    """Clé d'anti-rejeu d'un event : sa `dedup_key` naturelle, sinon `seq:<n>`."""
    return event.get("dedup_key") or f"seq:{event['seq']}"


def build_context(event: dict[str, Any]) -> dict[str, str]:
    """Variables de template exposées par un event (racine + subject.*)."""
    ctx: dict[str, str] = {
        "actor": str(event.get("actor", "")),
        "workspace": str(event.get("workspace") or ""),
        "type": str(event.get("event_type", "")),
        "seq": str(event.get("seq", "")),
    }
    # Namespace canonique `event.*` : racine + champs du subject, tous préfixés.
    ctx["event.type"] = ctx["type"]
    ctx["event.actor"] = ctx["actor"]
    ctx["event.workspace"] = ctx["workspace"]
    ctx["event.seq"] = ctx["seq"]
    subject = event.get("subject") or {}
    for key, value in subject.items():
        sval = "" if value is None else str(value)
        ctx[f"subject.{key}"] = sval
        ctx.setdefault(key, sval)
        ctx[f"event.{key}"] = sval  # forme canonique exposée à la palette
    # Alias `user.*` (compat des templates existants sur events user.*).
    if str(event.get("event_type", "")).startswith("user."):
        for prop in ("login", "sub", "identity", "email"):
            raw = subject.get(prop)
            ctx[f"user.{prop}"] = "" if raw is None else str(raw)
    return ctx


def render_template(template: str, context: dict[str, str]) -> str:
    """Substitue `{var}` par sa valeur ; laisse `{var}` inconnu intact (debuggable)."""

    def _sub(m: re.Match[str]) -> str:
        name = m.group(1)
        return context[name] if name in context else m.group(0)

    return _VAR_RE.sub(_sub, template)


# Référence de secret système résolvable en tâche de fond (KEK, sans PIN utilisateur).
_SYSTEM_REF_RE = re.compile(r"^\$\{system://([a-z0-9][a-z0-9_-]*)\}$")


def _resolve_headers_blocking(headers: list[dict[str, Any]]) -> dict[str, str]:
    """Résout les secret_ref vault globaux → {name: valeur révélée}. Bloquant."""
    from ..config.store import load_global, safe_user_path
    from ..secrets.factory import create_backend
    from ..secrets.resolver import Scope, resolve
    from ..secrets.types import Secret

    cfg = load_global()
    backend = create_backend(
        backend_type=cfg.secrets.backend,
        url=cfg.secrets.harpocrate.url,
        api_key=cfg.secrets.harpocrate.api_key,
        base_path=cfg.secrets.harpocrate.base_path,
        user_secrets_path=safe_user_path("__system__", "secrets.yaml"),
    )
    scope = Scope(kind="global")
    out: dict[str, str] = {}
    for hdr in headers:
        val = resolve(hdr["secret_ref"], scope, backend)
        out[hdr["name"]] = val.reveal() if isinstance(val, Secret) else str(val)
    return out


async def _resolve_headers(headers: list[dict[str, Any]]) -> dict[str, str]:
    """Résout les en-têtes actifs. `${system://slug}` via KEK (fond), sinon vault global.

    La valeur finale = `value_prefix` + secret/valeur (ex. « Bearer » + token).
    En-têtes désactivés ou sans valeur ni secret (stub d'auth) → ignorés.
    """
    from ..secrets.system import reveal_system_secret

    out: dict[str, str] = {}
    vault_headers: list[dict[str, Any]] = []
    for hdr in headers:
        if not hdr.get("enabled", True):
            continue
        name = hdr["name"]
        prefix = hdr.get("value_prefix") or ""
        ref = hdr.get("secret_ref")
        if ref:
            m = _SYSTEM_REF_RE.match(ref)
            if m:
                async with _get_engine().begin() as conn:
                    secret = await reveal_system_secret(m.group(1), conn)
                out[name] = prefix + secret
            else:
                vault_headers.append(hdr)
        elif hdr.get("value") is not None:
            out[name] = prefix + str(hdr["value"])
    if vault_headers:
        revealed = await asyncio.to_thread(_resolve_headers_blocking, vault_headers)
        for hdr in vault_headers:
            if hdr["name"] in revealed:
                out[hdr["name"]] = (hdr.get("value_prefix") or "") + revealed[hdr["name"]]
    return out


# ─── Exécution de l'arbre de règle ───────────────────────────────────────────

# Bornes de la trace persistée (un item par nœud exécuté) et de l'aplatissement
# d'une réponse nommée dans le contexte de template.
_TRACE_MAX_ITEMS = 200
_TRACE_PREVIEW = 500
_FLAT_MAX_ENTRIES = 200
_FLAT_MAX_DEPTH = 6
_FLAT_MAX_LIST = 20

_KEY_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def flatten_response(name: str, data: Any, ctx: dict[str, str]) -> None:
    """Expose la réponse JSON d'un appel nommé aux templates aval.

    `{"id": 7, "tags": ["a"]}` sous le nom `create` → `{create.id}`, `{create.tags.0}`.
    Bornes défensives (profondeur, listes, nombre d'entrées) : une réponse énorme
    n'inonde pas le contexte. Clés non sûres pour un nom de variable ignorées.
    """
    budget = _FLAT_MAX_ENTRIES

    def _rec(prefix: str, val: Any, depth: int) -> None:
        nonlocal budget
        if budget <= 0 or depth > _FLAT_MAX_DEPTH:
            return
        if isinstance(val, dict):
            for k, v in val.items():
                if _KEY_RE.fullmatch(str(k)):
                    _rec(f"{prefix}.{k}", v, depth + 1)
        elif isinstance(val, list):
            for i, v in enumerate(val[:_FLAT_MAX_LIST]):
                _rec(f"{prefix}.{i}", v, depth + 1)
        else:
            if isinstance(val, bool):
                sval = "true" if val else "false"
            else:
                sval = "" if val is None else str(val)
            ctx[prefix] = sval
            budget -= 1

    _rec(name, data, 0)


class _CallFailed(Exception):
    """Échec d'un appel de l'arbre : toute la règle s'arrête (fail-fast, rejouable)."""


class _TreeWalk:
    """Parcours en profondeur d'un arbre de règle pour UN event.

    Filtre du bloc (arbre ET/OU, court-circuit, fail closed) → s'il passe, appels
    (chaque réponse JSON aplatie dans le contexte sous son nom) puis blocs enfants ;
    sinon le sous-arbre est sauté et le bloc frère suivant continue.
    """

    def __init__(self, ctx: dict[str, str], client: httpx.AsyncClient) -> None:
        self.ctx = ctx
        self.client = client
        self.trace: list[dict[str, Any]] = []
        self.calls_run = 0
        self.last_http: int | None = None

    def _add(self, item: dict[str, Any]) -> None:
        if len(self.trace) < _TRACE_MAX_ITEMS:
            self.trace.append(item)

    async def _node_headers(self, node: Any, *, json_body: bool) -> dict[str, str]:
        """Résout les en-têtes propres au nœud (value/`${…}` → valeur révélée)."""
        headers = await _resolve_headers([h.model_dump() for h in node.headers])
        if json_body:
            headers.setdefault("content-type", "application/json")
        return headers

    async def eval_filter(self, node: Any, path: str) -> bool:
        from . import filter_eval as feval
        from .tree import TreeFilterGroup

        if isinstance(node, TreeFilterGroup):
            passed = node.op == "and"
            for i, child in enumerate(node.items):
                sub = await self.eval_filter(child, f"{path}.{i}")
                if node.op == "and" and not sub:
                    passed = False
                    break  # court-circuit ET
                if node.op == "or" and sub:
                    passed = True
                    break  # court-circuit OU
                passed = sub
            self._add({"path": path, "kind": "filter_group", "op": node.op, "passed": passed})
            return passed

        r_url = render_template(node.url, self.ctx)
        r_jsonpath = render_template(node.jsonpath, self.ctx)
        r_expected = render_template(node.expected, self.ctx) if node.expected else None
        body = render_template(node.body, self.ctx) if node.body else None
        preview = f"{node.http_method} {r_url} :: {r_jsonpath} {node.operator} {r_expected or ''}"
        item: dict[str, Any] = {"path": path, "kind": "filter", "preview": preview.rstrip()}
        try:
            headers = await self._node_headers(node, json_body=body is not None)
            resp = await pinned_request(
                self.client,
                node.http_method,
                r_url,
                headers=headers,
                content=body.encode() if body is not None else None,
                timeout=15.0,
                max_bytes=_RESP_PREVIEW_MAX,
            )
            passed, matched = feval.evaluate(resp.json(), r_jsonpath, node.operator, r_expected)
            item.update(
                passed=passed,
                http_status=resp.status_code,
                detail=f"matches={matched!r}"[:_TRACE_PREVIEW],
            )
        except Exception as exc:
            # Fail closed : on n'agit jamais sur un état incertain.
            item.update(passed=False, detail=f"{type(exc).__name__}: {exc}"[:_TRACE_PREVIEW])
        self._add(item)
        return bool(item["passed"])

    async def run_call(self, call: Any, path: str) -> None:
        r_url = render_template(call.url, self.ctx)
        body = render_template(call.body_template, self.ctx) if call.body_template else None
        preview = f"{call.http_method} {r_url}" + (f"\n{body}" if body else "")
        item: dict[str, Any] = {
            "path": path,
            "kind": "call",
            "name": call.name,
            "preview": preview[:_TRACE_PREVIEW],
        }
        try:
            headers = await self._node_headers(call, json_body=body is not None)
            resp = await pinned_request(
                self.client,
                call.http_method,
                r_url,
                headers=headers,
                content=body.encode() if body is not None else None,
                timeout=15.0,
                max_bytes=_RESP_PREVIEW_MAX,
            )
        except Exception as exc:
            item.update(status="failed", detail=f"{type(exc).__name__}: {exc}"[:_TRACE_PREVIEW])
            self._add(item)
            raise _CallFailed(f"appel {call.name!r} : {type(exc).__name__}: {exc}") from exc
        self.last_http = resp.status_code
        item["http_status"] = resp.status_code
        if not (httpx.codes.OK <= resp.status_code < 300):
            item.update(status="failed", detail=resp.text[:_TRACE_PREVIEW])
            self._add(item)
            raise _CallFailed(f"appel {call.name!r} : HTTP {resp.status_code}")
        self.calls_run += 1
        item.update(status="ok", detail=resp.text[:_TRACE_PREVIEW])
        self._add(item)
        # Réponse non-JSON : rien à exposer dans le contexte, l'appel reste OK.
        with contextlib.suppress(ValueError):
            flatten_response(call.name, resp.json(), self.ctx)

    async def run_block(self, block: Any, path: str) -> None:
        if block.filter is not None and not await self.eval_filter(block.filter, f"{path}.filter"):
            self._add({"path": path, "kind": "block", "label": block.label, "passed": False})
            return  # sous-arbre sauté, le bloc frère suivant continue
        for i, call in enumerate(block.calls):
            await self.run_call(call, f"{path}.calls.{i}")
        for j, child in enumerate(block.blocks):
            await self.run_block(child, f"{path}.blocks.{j}")


async def _execute(
    automation: dict[str, Any], event: dict[str, Any], client: httpx.AsyncClient, *, manual: bool
) -> str:
    """Claim (sauf rejeu manuel) + parcours de l'arbre + finish. ok|failed|skipped.

    `ok` = au moins un appel exécuté, aucun en échec ; `skipped` = tous les blocs
    filtrés (ou arbre vide) ; `failed` = arbre/headers invalides ou appel en échec
    (fail-fast : la règle s'arrête au premier appel KO, le run est rejouable).
    """
    from .tree import RuleTree

    aid = automation["id"]
    key = dedup_key(event)
    run_id: str | None = None
    if not manual:
        async with _get_engine().begin() as conn:
            run_id = await ar.claim(conn, automation_id=aid, event_seq=event["seq"], dedup_key=key)
        if run_id is None:
            return "skipped"  # déjà traité (anti-rejeu)

    walk: _TreeWalk | None = None

    async def _finish(status: str, *, error: str | None = None) -> str:
        calls = walk.calls_run if walk is not None else 0
        fields: dict[str, Any] = {
            "status": status,
            "http_status": walk.last_http if walk is not None else None,
            "request_preview": f"tree v1 : {calls} appel(s) exécuté(s)",
            "response_preview": None,
            "error": error,
            "trace": walk.trace if walk is not None else None,
        }
        async with _get_engine().begin() as conn:
            if manual:
                await ar.record_manual(
                    conn, automation_id=aid, event_seq=event["seq"], dedup_key=key, **fields
                )
            else:
                assert run_id is not None
                await ar.finish(conn, run_id, **fields)
        return status

    try:
        tree = RuleTree.model_validate(automation.get("tree") or {})
    except Exception as exc:
        return await _finish("failed", error=f"arbre de règle invalide : {exc}")

    walk = _TreeWalk(build_context(event), client)
    try:
        for i, block in enumerate(tree.blocks):
            await walk.run_block(block, str(i))
    except _CallFailed as exc:
        return await _finish("failed", error=str(exc))
    except Exception as exc:  # garde-fou : jamais de crash du balayage
        return await _finish("failed", error=f"{type(exc).__name__}: {exc}")
    if walk.calls_run == 0:
        return await _finish("skipped", error="aucun appel exécuté (filtres non passés)")
    return await _finish("ok")


async def _record_skipped(automation_id: str, event: dict[str, Any], *, reason: str) -> None:
    """Trace un run `skipped` (bloqué par stop_chain) — anti-rejeu inclus."""
    async with _get_engine().begin() as conn:
        run_id = await ar.claim(
            conn, automation_id=automation_id, event_seq=event["seq"], dedup_key=dedup_key(event)
        )
        if run_id is not None:
            await ar.finish(conn, run_id, status="skipped", error=reason)


async def process_once(*, now: datetime | None = None) -> dict[str, int]:
    """Un balayage du journal par curseur pour tous les automates actifs."""
    now = now or datetime.now(UTC)
    counts = {"ok": 0, "failed": 0, "skipped": 0}

    async with _get_engine().connect() as conn:
        autos = await adb.list_active(conn)
    if not autos:
        return counts

    cursors = {a["id"]: a["last_seq"] for a in autos}
    new_cursor = dict(cursors)
    stalled: set[str] = set()

    async with _get_engine().connect() as conn:
        events = await je.read_after(conn, after_seq=min(cursors.values()), limit=_BATCH)
    if not events:
        return counts

    async with httpx.AsyncClient() as client:
        for event in events:
            seq = event["seq"]
            consumed = False
            for auto in autos:
                aid = auto["id"]
                if aid in stalled or new_cursor[aid] >= seq:
                    continue
                if not matches(auto, event):
                    new_cursor[aid] = seq
                    continue
                delay = auto["delay_minutes"]
                if delay > 0 and (now - event["occurred_at"]) < timedelta(minutes=delay):
                    stalled.add(aid)  # trop jeune : caler, curseur non avancé au-delà
                    continue
                if consumed:
                    await _record_skipped(aid, event, reason="stop_chain")
                    new_cursor[aid] = seq
                    counts["skipped"] += 1
                    continue
                outcome = await _execute(auto, event, client, manual=False)
                new_cursor[aid] = seq
                counts[outcome] += 1
                if outcome == "ok" and auto["stop_chain"]:
                    consumed = True

    async with _get_engine().begin() as conn:
        for aid, seq in new_cursor.items():
            if seq != cursors[aid]:
                await adb.set_cursor(conn, aid, seq)
    return counts


async def replay_run(automation_id: str, run_id: str) -> dict[str, Any] | None:
    """Rejoue manuellement un run passé (re-résout et ré-appelle). None si introuvable."""
    async with _get_engine().connect() as conn:
        automation = next((a for a in await adb.list_all(conn) if a["id"] == automation_id), None)
        run = await ar.get_run(conn, run_id)
    if automation is None or run is None or run["automation_id"] != automation_id:
        return None
    async with _get_engine().connect() as conn:
        event = await je.get(conn, run["event_seq"])
    if event is None:
        return None
    async with httpx.AsyncClient() as client:
        status = await _execute(automation, event, client, manual=True)
    return {"status": status, "event_seq": run["event_seq"]}


async def runner_loop(interval_s: float = _DEFAULT_INTERVAL_S) -> None:
    """Boucle de fond : balaie le journal et exécute les automates dus."""
    await asyncio.sleep(3)  # laisse le portail démarrer
    async with _get_engine().begin() as conn:
        reset = await ar.reset_stale_running(conn)  # reprise at-least-once
    if reset:
        _log.info("automation_runs_reset_stale", count=reset)
    while True:
        try:
            counts = await process_once()
            if counts["ok"] or counts["failed"] or counts["skipped"]:
                _log.info("automations_swept", **counts)
        except Exception:
            _log.warning("automation_runner_loop_failed", exc_info=True)
        await asyncio.sleep(interval_s)
