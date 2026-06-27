# backend/tests/test_bundled_recipes.py
from __future__ import annotations

from pathlib import Path


def _write_recipe(base: Path, rid: str, body: str) -> None:
    d = base / rid
    d.mkdir(parents=True)
    (d / "recipe.meta.yaml").write_text(body, encoding="utf-8")


def test_bundled_recipes_lists_initialize_with_local_source_url(tmp_path, monkeypatch) -> None:
    from portal.routes import recipe_sources as rs

    _write_recipe(
        tmp_path,
        "claude-bypass-permissions",
        "id: claude-bypass-permissions\n"
        "type: initialize\n"
        "description: demo\n"
        "transform:\n"
        "  - op: remove\n"
        "    target:\n"
        "      file: /home/vscode/.claude/settings.json\n"
        "      node: $.permissions\n",
    )
    monkeypatch.setattr(rs, "_bundled_bases", lambda: [tmp_path])

    out = rs._bundled_recipes()
    assert len(out) == 1
    entry = out[0]
    assert entry["id"] == "claude-bypass-permissions"
    assert entry["type"] == "initialize"
    assert entry["source_url"] == "local:claude-bypass-permissions"
    assert entry["install_script"] == ""  # pas d'install.sh pour une initialize


def test_bundled_recipes_dedup_by_id(tmp_path, monkeypatch) -> None:
    from portal.routes import recipe_sources as rs

    base1 = tmp_path / "a"
    base2 = tmp_path / "b"
    _write_recipe(base1, "dup", "id: dup\ntype: install\n")
    _write_recipe(base2, "dup", "id: dup\ntype: install\n")
    monkeypatch.setattr(rs, "_bundled_bases", lambda: [base1, base2])

    out = rs._bundled_recipes()
    assert len(out) == 1  # déduplication par id (première base gagne)
