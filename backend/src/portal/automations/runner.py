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
_RUN_HISTORY_KEEP = 20
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
    subject = event.get("subject") or {}
    for key, value in subject.items():
        ctx[f"subject.{key}"] = "" if value is None else str(value)
        ctx.setdefault(key, "" if value is None else str(value))
    # Namespace `user.*` (propriétés de la table user) pour les events user.* :
    # login/sub/identity/email garantis (défaut "") — aucun {user.x} laissé littéral.
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


async def _run_filter(
    automation: dict[str, Any], ctx: dict[str, str], client: httpx.AsyncClient
) -> tuple[bool, str, str | None]:
    """Gate de filtre. `(passe, aperçu requête, aperçu réponse)`.

    Pas de filtre configuré → passe. Erreur d'appel/évaluation → **fail closed**
    (ne passe pas) : on n'agit jamais sur un état incertain.
    """
    from . import filter_eval as feval

    op = automation.get("filter_operator")
    furl = automation.get("filter_url")
    jsonpath = automation.get("filter_jsonpath")
    if not (op and furl and jsonpath):
        return True, "", None
    method = automation.get("filter_method") or "GET"
    r_url = render_template(furl, ctx)
    r_jsonpath = render_template(jsonpath, ctx)
    expected = automation.get("filter_expected")
    r_expected = render_template(expected, ctx) if expected else None
    fbody = automation.get("filter_body")
    body = render_template(fbody, ctx) if fbody else None
    preview = f"[filtre] {method} {r_url} :: {r_jsonpath} {op} {r_expected or ''}".rstrip()
    try:
        headers = await _resolve_headers(automation["headers"])
        if body is not None:
            headers.setdefault("content-type", "application/json")
        resp = await pinned_request(
            client,
            method,
            r_url,
            headers=headers,
            content=body.encode() if body is not None else None,
            timeout=15.0,
            max_bytes=_RESP_PREVIEW_MAX,
        )
        passed, matches = feval.evaluate(resp.json(), r_jsonpath, op, r_expected)
        return passed, preview, f"passe={passed} matches={matches!r}\n{resp.text[:2000]}"
    except Exception as exc:
        return False, preview, f"filter_error: {type(exc).__name__}: {exc}"


async def _execute(
    automation: dict[str, Any], event: dict[str, Any], client: httpx.AsyncClient, *, manual: bool
) -> str:
    """Claim (sauf rejeu manuel) + filtre + appel HTTP + finish. Retourne ok|failed|skipped."""
    aid = automation["id"]
    key = dedup_key(event)
    if not manual:
        async with _get_engine().begin() as conn:
            run_id = await ar.claim(conn, automation_id=aid, event_seq=event["seq"], dedup_key=key)
        if run_id is None:
            return "skipped"  # déjà traité (anti-rejeu)

    ctx = build_context(event)

    # Gate de filtre : si configuré et non passé, on n'appelle pas (run tracé « skipped »).
    passed, f_preview, f_resp = await _run_filter(automation, ctx, client)
    if not passed:
        async with _get_engine().begin() as conn:
            if manual:
                await ar.record_manual(
                    conn,
                    automation_id=aid,
                    event_seq=event["seq"],
                    dedup_key=key,
                    status="skipped",
                    http_status=None,
                    request_preview=f_preview,
                    response_preview=f_resp,
                    error="filtré",
                )
            else:
                await ar.finish(
                    conn,
                    run_id,  # type: ignore[arg-type]  # non-None dans la branche non-manuelle
                    status="skipped",
                    http_status=None,
                    request_preview=f_preview,
                    response_preview=f_resp,
                    error="filtré",
                )
            await ar.prune(conn, aid, keep=_RUN_HISTORY_KEEP)
        return "skipped"

    url = render_template(automation["url"], ctx)
    tmpl = automation["body_template"]
    body = render_template(tmpl, ctx) if tmpl else None
    method = automation["http_method"]
    preview = f"{method} {url}" + (f"\n{body}" if body else "")

    try:
        headers = await _resolve_headers(automation["headers"])
        if body is not None:
            headers.setdefault("content-type", "application/json")
        resp = await pinned_request(
            client,
            method,
            url,
            headers=headers,
            content=body.encode() if body is not None else None,
            timeout=15.0,
            max_bytes=_RESP_PREVIEW_MAX,
        )
        status = "ok" if httpx.codes.OK <= resp.status_code < 300 else "failed"
        error = None if status == "ok" else f"HTTP {resp.status_code}"
        resp_preview: str | None = resp.text
        http_status: int | None = resp.status_code
    except Exception as exc:
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"
        resp_preview = None
        http_status = None

    async with _get_engine().begin() as conn:
        if manual:
            await ar.record_manual(
                conn,
                automation_id=aid,
                event_seq=event["seq"],
                dedup_key=key,
                status=status,
                http_status=http_status,
                request_preview=preview,
                response_preview=resp_preview,
                error=error,
            )
        else:
            await ar.finish(
                conn,
                run_id,  # type: ignore[arg-type]  # non-None dans la branche non-manuelle
                status=status,
                http_status=http_status,
                request_preview=preview,
                response_preview=resp_preview,
                error=error,
            )
        await ar.prune(conn, aid, keep=_RUN_HISTORY_KEEP)
    return status


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
