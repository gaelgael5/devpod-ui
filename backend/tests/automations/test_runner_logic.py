"""Logique pure du runner : matching (type + portée), dedup_key, contexte, template."""

from __future__ import annotations

import pytest

from portal.automations import runner as r


def _event(**over: object) -> dict:
    base = {
        "seq": 5,
        "event_type": "test_server.updated",
        "actor": "alice",
        "workspace": "proj",
        "subject": {"host_name": "h1", "address": "root@1.2.3.4", "password_changed": True},
        "dedup_key": None,
    }
    base.update(over)
    return base


def _auto(**over: object) -> dict:
    base = {
        "event_types": ["test_server.updated"],
        "delay_minutes": 0,
        "stop_chain": False,
    }
    base.update(over)
    return base


def test_matches_on_type() -> None:
    # Le matching ne dépend QUE du type d'event (plus de filtre par workspace).
    assert r.matches(_auto(), _event()) is True
    assert r.matches(_auto(), _event(workspace="autre")) is True


def test_no_match_on_type() -> None:
    assert r.matches(_auto(event_types=["session.created"]), _event()) is False


def test_dedup_key_prefers_natural_then_seq() -> None:
    assert r.dedup_key(_event(dedup_key="host:h1")) == "host:h1"
    assert r.dedup_key(_event(dedup_key=None, seq=42)) == "seq:42"


def test_build_context_event_namespace() -> None:
    ev = {
        "seq": 1,
        "event_type": "user.created",
        "actor": "alice",
        "subject": {"login": "alice", "sub": "S-1", "email": "a@x.org", "identity": None},
    }
    ctx = r.build_context(ev)
    assert ctx["event.type"] == "user.created"
    assert ctx["event.actor"] == "alice"
    assert ctx["event.login"] == "alice"
    assert ctx["event.sub"] == "S-1"
    assert ctx["event.email"] == "a@x.org"
    assert ctx["event.identity"] == ""  # None → "" (jamais littéral)
    assert ctx["user.sub"] == "S-1"  # alias de compat conservé


def test_build_context_no_user_namespace_for_non_user_event() -> None:
    ctx = r.build_context(_event())  # test_server.updated
    assert "user.sub" not in ctx


def test_build_context_exposes_root_and_subject() -> None:
    ctx = r.build_context(_event())
    assert ctx["actor"] == "alice"
    assert ctx["workspace"] == "proj"
    assert ctx["type"] == "test_server.updated"
    assert ctx["subject.host_name"] == "h1"
    assert ctx["host_name"] == "h1"  # alias plat
    assert ctx["subject.password_changed"] == "True"


def test_render_template_substitutes_known_leaves_unknown() -> None:
    tmpl = '{"name":"{subject.host_name}","addr":"{address}","who":"{actor}","x":"{missing}"}'
    ctx = r.build_context(_event())
    out = r.render_template(tmpl, ctx)
    assert '"name":"h1"' in out
    assert '"addr":"root@1.2.3.4"' in out
    assert '"who":"alice"' in out
    assert '"x":"{missing}"' in out  # inconnu laissé intact


def test_system_ref_regex_matches_slug() -> None:
    m = r._SYSTEM_REF_RE.match("${system://termix-apikey}")
    assert m is not None and m.group(1) == "termix-apikey"
    # Rejette les slugs invalides et les autres schémas.
    assert r._SYSTEM_REF_RE.match("${vault://foo}") is None
    assert r._SYSTEM_REF_RE.match("${system://Bad Slug}") is None


def test_flatten_response_paths_and_bounds() -> None:
    ctx: dict[str, str] = {}
    r.flatten_response("create", {"id": 7, "ok": True, "tags": ["a", "b"], "nul": None}, ctx)
    assert ctx == {
        "create.id": "7",
        "create.ok": "true",
        "create.tags.0": "a",
        "create.tags.1": "b",
        "create.nul": "",
    }
    # Clé non sûre pour un nom de variable → ignorée.
    ctx2: dict[str, str] = {}
    r.flatten_response("x", {"a b": 1, "ok": 2}, ctx2)
    assert ctx2 == {"x.ok": "2"}


def _mock_walk(handler: object, ctx: dict[str, str] | None = None):  # noqa: ANN202
    import httpx

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return r._TreeWalk(ctx or {}, {}, client), client


def _unpin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Court-circuite l'anti-SSRF (MockTransport ne résout pas de DNS)."""

    async def _unpinned(client, method, url, **kw):  # noqa: ANN001, ANN202
        kw.pop("max_bytes", None)
        return await client.request(method, url, **kw)

    monkeypatch.setattr(r, "pinned_request", _unpinned)


@pytest.mark.asyncio
async def test_treewalk_filter_gate_and_response_chaining(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from portal.automations.tree import RuleTree

    _unpin(monkeypatch)
    calls_seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls_seen.append(f"{req.method} {req.url.path}")
        if req.url.path == "/check":
            return httpx.Response(200, json={"ok": True})
        if req.url.path == "/create":
            return httpx.Response(201, json={"id": 42})
        if req.url.path == "/use":
            assert req.url.params["id"] == "42"  # réponse nommée chaînée
            return httpx.Response(200, json={})
        return httpx.Response(500)

    tree = RuleTree.model_validate(
        {
            "blocks": [
                {
                    "filter": {"url": "https://x/check", "jsonpath": "$.ok", "operator": "exists"},
                    "calls": [{"name": "create", "url": "https://x/create", "http_method": "POST"}],
                    "blocks": [
                        {
                            "calls": [
                                {
                                    "name": "use",
                                    "url": "https://x/use?id={create.id}",
                                    "http_method": "GET",
                                }
                            ]
                        }
                    ],
                },
                {
                    # Filtre non passé → sous-arbre sauté, pas d'appel /never.
                    "filter": {
                        "url": "https://x/check",
                        "jsonpath": "$.missing",
                        "operator": "exists",
                    },
                    "calls": [{"name": "never", "url": "https://x/never", "http_method": "GET"}],
                },
            ]
        }
    )
    walk, client = _mock_walk(handler)
    for i, block in enumerate(tree.blocks):
        await walk.run_block(block, str(i))
    await client.aclose()

    assert walk.calls_run == 2
    assert "GET /never" not in calls_seen
    kinds = [(t["kind"], t.get("passed", t.get("status"))) for t in walk.trace]
    assert ("filter", True) in kinds and ("call", "ok") in kinds and ("block", False) in kinds


@pytest.mark.asyncio
async def test_treewalk_call_failure_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from portal.automations.tree import RuleTree

    _unpin(monkeypatch)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    tree = RuleTree.model_validate(
        {"blocks": [{"calls": [{"name": "ko", "url": "https://x/do", "http_method": "POST"}]}]}
    )
    walk, client = _mock_walk(handler)
    with pytest.raises(r._CallFailed, match="HTTP 500"):
        await walk.run_block(tree.blocks[0], "0")
    await client.aclose()
    assert walk.calls_run == 0 and walk.last_http == 500


@pytest.mark.asyncio
async def test_treewalk_nested_and_or_short_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from portal.automations.tree import RuleTree

    _unpin(monkeypatch)
    hits: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        hits.append(req.url.path)
        return httpx.Response(200, json={"ok": req.url.path == "/yes"})

    leaf_yes = {
        "url": "https://x/yes",
        "jsonpath": "$.ok",
        "operator": "equals",
        "expected": "true",
    }
    leaf_no = {"url": "https://x/no", "jsonpath": "$.ok", "operator": "equals", "expected": "true"}
    tree = RuleTree.model_validate(
        {
            "blocks": [
                {
                    "filter": {
                        "op": "and",
                        "items": [leaf_yes, {"op": "or", "items": [leaf_yes, leaf_no]}],
                    },
                    "calls": [{"name": "go", "url": "https://x/yes", "http_method": "GET"}],
                }
            ]
        }
    )
    walk, client = _mock_walk(handler)
    await walk.run_block(tree.blocks[0], "0")
    await client.aclose()
    # OU court-circuité : /no jamais appelé ; le call final est parti.
    assert "/no" not in hits and walk.calls_run == 1


@pytest.mark.asyncio
async def test_resolve_headers_value_prefix_and_flags() -> None:
    headers = [
        {"name": "X-Api-Key", "value": "abc", "secret_ref": None, "value_prefix": ""},
        {"name": "Authorization", "value": "tok", "secret_ref": None, "value_prefix": "Bearer "},
        {"name": "X-Off", "value": "z", "secret_ref": None, "enabled": False},
        {"name": "X-Stub", "value": None, "secret_ref": None},  # auth non configuré
    ]
    out = await r._resolve_headers(headers)
    assert out == {"X-Api-Key": "abc", "Authorization": "Bearer tok"}
