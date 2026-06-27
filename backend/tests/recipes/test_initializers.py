# backend/tests/recipes/test_initializers.py
from __future__ import annotations

import asyncio
import base64
import re
from pathlib import Path

from portal.recipes import initializers as I
from portal.recipes.models import RecipeMeta


def _meta_transform() -> RecipeMeta:
    return RecipeMeta(
        id="claude-bypass-permissions",
        type="initialize",
        version="1.0.0",
        transform=[
            {
                "op": "replace",
                "target": {"file": "/home/vscode/.claude/settings.json", "node": "$.permissions"},
                "value": {"allow": [], "defaultMode": "bypassPermissions"},
            }
        ],
    )


def _decode_remote_script(remote_cmd: str) -> str:
    m = re.search(r"printf %s '([A-Za-z0-9+/=]+)'", remote_cmd)
    assert m, remote_cmd
    return base64.b64decode(m.group(1)).decode("utf-8")


# ── build_spec ────────────────────────────────────────────────────────────────


def test_build_spec_transform_replace() -> None:
    spec = I.build_spec(_meta_transform())
    assert spec["recipe_id"] == "claude-bypass-permissions"
    assert spec["version"] == "1.0.0"
    assert spec["copy"] == []
    assert spec["transform"][0]["op"] == "replace"
    assert spec["transform"][0]["value"]["defaultMode"] == "bypassPermissions"


def test_build_spec_remove_omits_value() -> None:
    meta = RecipeMeta(
        id="x",
        type="initialize",
        transform=[{"op": "remove", "target": {"file": "/a/b.json", "node": "$.k"}}],
    )
    spec = I.build_spec(meta)
    assert "value" not in spec["transform"][0]


# ── build_remote_cmd ──────────────────────────────────────────────────────────


def test_build_remote_cmd_guards_python_and_no_force() -> None:
    cmd = I.build_remote_cmd(_meta_transform(), Path("/nonexistent"), force=False)
    script = _decode_remote_script(cmd)
    assert "command -v python3" in script
    assert 'python3 "$D/r.py" \n' in script or 'python3 "$D/r.py" ' in script
    assert "--force" not in script
    assert "--src" not in script  # pas de copy


def test_build_remote_cmd_force_flag() -> None:
    cmd = I.build_remote_cmd(_meta_transform(), Path("/nonexistent"), force=True)
    assert "--force" in _decode_remote_script(cmd)


def test_build_remote_cmd_with_copy_adds_tar_and_src(tmp_path: Path) -> None:
    (tmp_path / "files" / "claude").mkdir(parents=True)
    (tmp_path / "files" / "claude" / "a.txt").write_text("x", encoding="utf-8")
    meta = RecipeMeta(
        id="x",
        type="initialize",
        copy=[{"source": "files/claude", "target": "/home/vscode/.claude"}],
    )
    script = _decode_remote_script(I.build_remote_cmd(meta, tmp_path, force=False))
    assert "tar -xzf" in script
    assert "--src" in script


# ── _parse_result ─────────────────────────────────────────────────────────────


def test_parse_result_last_json_line() -> None:
    out = 'noise\n{"applied": true, "already_applied": false, "message": "applied"}\n'
    res = I._parse_result(out)
    assert res is not None and res["applied"] is True


def test_parse_result_none_when_absent() -> None:
    assert I._parse_result("just logs\nno json here") is None


# ── locate_recipe_dir ─────────────────────────────────────────────────────────


def test_locate_recipe_dir_shared(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(I, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(
        I, "safe_user_path", lambda login, *p: tmp_path / "users" / login / Path(*p)
    )
    (tmp_path / "recipes" / "demo").mkdir(parents=True)
    found = I.locate_recipe_dir("alice", "demo")
    assert found == tmp_path / "recipes" / "demo"


def test_locate_recipe_dir_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(I, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(
        I, "safe_user_path", lambda login, *p: tmp_path / "users" / login / Path(*p)
    )
    assert I.locate_recipe_dir("alice", "nope") is None


# ── run_initializer (SSH mocké) ───────────────────────────────────────────────


def _patch_ssh(monkeypatch, rc: int, out: str, err: str = "") -> None:
    async def _fake(login, ws_id, remote_cmd, *, timeout=60.0):
        return (rc, out, err)

    monkeypatch.setattr(I, "run_ssh_capture", _fake)


def test_run_initializer_applied(monkeypatch) -> None:
    _patch_ssh(monkeypatch, 0, '{"applied": true, "already_applied": false, "message": "applied"}')
    res = asyncio.run(
        I.run_initializer("alice", "ws1", _meta_transform(), Path("/nonexistent"), force=False)
    )
    assert res["applied"] is True
    assert res["already_applied"] is False


def test_run_initializer_already_applied(monkeypatch) -> None:
    _patch_ssh(monkeypatch, 0, '{"applied": false, "already_applied": true, "message": "x"}')
    res = asyncio.run(
        I.run_initializer("alice", "ws1", _meta_transform(), Path("/nonexistent"), force=False)
    )
    assert res["already_applied"] is True


def test_run_initializer_error_raises(monkeypatch) -> None:
    import pytest

    _patch_ssh(
        monkeypatch,
        1,
        '{"applied": false, "already_applied": false, "error": "python3 not found in container"}',
    )
    with pytest.raises(I.InitializerError, match="python3"):
        asyncio.run(
            I.run_initializer("alice", "ws1", _meta_transform(), Path("/nonexistent"), force=False)
        )


def test_run_initializer_no_result_raises(monkeypatch) -> None:
    import pytest

    _patch_ssh(monkeypatch, 255, "ssh: connect failed", "Permission denied")
    with pytest.raises(I.InitializerError):
        asyncio.run(
            I.run_initializer("alice", "ws1", _meta_transform(), Path("/nonexistent"), force=False)
        )
