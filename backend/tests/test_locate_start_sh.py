# backend/tests/test_locate_start_sh.py
from __future__ import annotations

from pathlib import Path


def _patch(monkeypatch, users: Path, data: Path, bundled: list[Path]) -> None:
    from portal.routes import workspace_sessions as ws

    monkeypatch.setattr(ws, "safe_user_path", lambda login, *p: users / login / Path(*p))
    monkeypatch.setattr(ws, "_data_root", lambda: data)
    monkeypatch.setattr(ws, "_bundled_recipe_bases", lambda: bundled)


def test_locate_start_sh_fallback_to_bundled(tmp_path, monkeypatch) -> None:
    from portal.routes import workspace_sessions as ws

    bundled = tmp_path / "app-recipes"
    (bundled / "start-x").mkdir(parents=True)
    (bundled / "start-x" / "start.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    _patch(monkeypatch, tmp_path / "users", tmp_path / "data", [bundled])

    assert ws.locate_start_sh("alice", "start-x") == bundled / "start-x" / "start.sh"


def test_locate_start_sh_prefers_data_over_bundled(tmp_path, monkeypatch) -> None:
    from portal.routes import workspace_sessions as ws

    data = tmp_path / "data"
    (data / "recipes" / "start-x").mkdir(parents=True)
    (data / "recipes" / "start-x" / "start.sh").write_text("data", encoding="utf-8")
    bundled = tmp_path / "app-recipes"
    (bundled / "start-x").mkdir(parents=True)
    (bundled / "start-x" / "start.sh").write_text("bundled", encoding="utf-8")
    _patch(monkeypatch, tmp_path / "users", data, [bundled])

    found = ws.locate_start_sh("alice", "start-x")
    assert found is not None and found.read_text(encoding="utf-8") == "data"


def test_locate_start_sh_none_when_absent(tmp_path, monkeypatch) -> None:
    from portal.routes import workspace_sessions as ws

    _patch(monkeypatch, tmp_path / "users", tmp_path / "data", [])
    assert ws.locate_start_sh("alice", "nope") is None
