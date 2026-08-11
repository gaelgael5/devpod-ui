"""Primitives MCP automation_rule_* : registre, validations, upsert (DB mockée)."""

from __future__ import annotations

import pytest

from portal.mcp.devpod_tools import _IMPLS
from portal.mcp.devpod_tools import automation_tools as at
from portal.mcp.devpod_tools.errors import DevpodToolError
from portal.mcp.devpod_tools.registry import DEVPOD_PRIMITIVES


def test_primitives_registered_with_admin_scope() -> None:
    for name in ("automation_rule_list", "automation_rule_get", "automation_rule_upsert"):
        assert name in DEVPOD_PRIMITIVES, name
        assert DEVPOD_PRIMITIVES[name]["scope"] == "admin"
        assert name in _IMPLS


@pytest.mark.asyncio
async def test_get_requires_slug() -> None:
    with pytest.raises(DevpodToolError, match="slug requis"):
        await at._rule_get(None, {}, "admin")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_upsert_rejects_invalid_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(DevpodToolError, match="arbre de règle invalide"):
        await at._rule_upsert(
            None,  # type: ignore[arg-type]
            {"slug": "r1", "tree": {"blocks": [{"filter": {"op": "and", "items": []}}]}},
            "admin",
        )


@pytest.mark.asyncio
async def test_upsert_rejects_unknown_event_type() -> None:
    with pytest.raises(DevpodToolError, match="event_types inconnus"):
        await at._rule_upsert(
            None,  # type: ignore[arg-type]
            {"slug": "r1", "event_types": ["nope.event"]},
            "admin",
        )


@pytest.mark.asyncio
async def test_upsert_create_requires_label_and_events(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _none(conn: object, slug: str) -> None:
        return None

    monkeypatch.setattr(at, "_by_slug", _none)
    with pytest.raises(DevpodToolError, match="label et event_types requis"):
        await at._rule_upsert(None, {"slug": "nouvelle"}, "admin")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_upsert_creates_with_normalized_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, object] = {}

    async def _none(conn: object, slug: str) -> None:
        return None

    async def _create(conn: object, **fields: object) -> dict[str, object]:
        created.update(fields)
        return {"id": "id1", **fields}

    async def _max_position(conn: object) -> int:
        return 3

    async def _set_cursor(conn: object, rule_id: str, seq: int) -> None:
        created["cursor"] = seq

    async def _latest_seq(conn: object) -> int:
        return 99

    async def _get(conn: object, rule_id: str) -> dict[str, object]:
        return {
            "id": "id1",
            "slug": "r1",
            "label": "Règle",
            "active": False,
            "event_types": ["workspace.created"],
            "position": 4,
            "stop_chain": False,
            "delay_minutes": 0,
            "tree": created["tree"],
        }

    monkeypatch.setattr(at, "_by_slug", _none)
    monkeypatch.setattr(at.adb, "create", _create)
    monkeypatch.setattr(at.adb, "max_position", _max_position)
    monkeypatch.setattr(at.adb, "set_cursor", _set_cursor)
    monkeypatch.setattr(at.adb, "get", _get)
    monkeypatch.setattr(at.je, "latest_seq", _latest_seq)

    out = await at._rule_upsert(
        None,  # type: ignore[arg-type]
        {
            "slug": "r1",
            "label": "Règle",
            "event_types": ["workspace.created"],
            "tree": {
                "blocks": [
                    {"calls": [{"name": "go", "url": "https://x/y", "http_method": "POST"}]}
                ]
            },
        },
        "admin",
    )
    assert out["created"] is True
    assert created["cursor"] == 99  # curseur au sommet du journal
    call = out["tree"]["blocks"][0]["calls"][0]
    assert call["body_template"] is None  # arbre normalisé (défauts matérialisés)
