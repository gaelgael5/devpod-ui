# backend/tests/recipes/test_initializers.py
"""Tests de l'orchestration initialize (inspection + application via SSH mocké).

Le conteneur n'exécute que du sh : les scripts générés ne doivent JAMAIS
dépendre de python3 côté conteneur.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from pathlib import Path

import pytest

from portal.recipes import initializers as I  # noqa: N812
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


# ── scripts générés : sh pur, pas de python3 ─────────────────────────────────


def test_inspect_cmd_is_pure_sh() -> None:
    script = _decode_remote_script(I.build_inspect_cmd(_meta_transform(), None))
    assert "python3" not in script
    assert "__PORTAL_SENTINEL__" in script
    assert "/home/vscode/.claude/.portal/claude-bypass-permissions@1.0.0" in script
    assert "base64 < /home/vscode/.claude/settings.json" in script


def test_apply_cmd_is_pure_sh_and_atomic(tmp_path: Path) -> None:
    meta = _meta_transform()
    new_files = {"/home/vscode/.claude/settings.json": '{"permissions": {}}\n'}
    script = _decode_remote_script(I.build_apply_cmd(meta, tmp_path, new_files))
    assert "python3" not in script
    # écriture tmp + mv dans le même dossier (atomicité)
    assert "/home/vscode/.claude/settings.json.portal-tmp" in script
    assert "mv /home/vscode/.claude/settings.json.portal-tmp" in script
    assert "__PORTAL_APPLIED__" in script


def test_apply_cmd_with_copy_dir_and_file(tmp_path: Path) -> None:
    (tmp_path / "files" / "claude").mkdir(parents=True)
    (tmp_path / "files" / "claude" / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "files" / "solo.json").write_text("{}", encoding="utf-8")
    meta = RecipeMeta(
        id="x",
        type="initialize",
        copy=[
            {"source": "files/claude", "target": "/home/vscode/.claude"},
            {"source": "files/solo.json", "target": "/home/vscode/solo.json"},
        ],
    )
    script = _decode_remote_script(I.build_apply_cmd(meta, tmp_path, {}))
    assert "tar -xzf" in script
    # dossier → copie du contenu ; fichier → mkdir parent + copie
    assert 'cp -a "$D/src/"files/claude/. /home/vscode/.claude/' in script
    assert 'cp -a "$D/src/"files/solo.json /home/vscode/solo.json' in script


def test_apply_cmd_no_ops_uses_home_sentinel(tmp_path: Path) -> None:
    meta = RecipeMeta(id="marker", type="initialize", version="2.0.0")
    script = _decode_remote_script(I.build_apply_cmd(meta, tmp_path, {}))
    assert '"$HOME"/.portal/marker@2.0.0' in script


# ── parse_inspect ─────────────────────────────────────────────────────────────


def _inspect_out(sentinel: bool, files: dict[str, str | None]) -> str:
    lines = [f"__PORTAL_SENTINEL__ {'1' if sentinel else '0'}"]
    for path, content in files.items():
        path_b64 = base64.b64encode(path.encode()).decode()
        lines.append(f"__PORTAL_FILE__ {path_b64}")
        if content is not None:
            lines.append(base64.b64encode(content.encode()).decode())
        lines.append("__PORTAL_EOF__")
    return "\n".join(lines) + "\n"


def test_parse_inspect_roundtrip() -> None:
    out = _inspect_out(True, {"/a.json": '{"k": 1}', "/absent.json": None})
    sentinel, files = I.parse_inspect(out)
    assert sentinel is True
    assert files["/a.json"] == '{"k": 1}'
    assert files["/absent.json"] is None


def test_parse_inspect_multiline_base64() -> None:
    content = json.dumps({"big": "x" * 200})
    b64 = base64.b64encode(content.encode()).decode()
    wrapped = "\n".join(b64[i : i + 76] for i in range(0, len(b64), 76))
    path_b64 = base64.b64encode(b"/big.json").decode()
    out = f"__PORTAL_SENTINEL__ 0\n__PORTAL_FILE__ {path_b64}\n{wrapped}\n__PORTAL_EOF__\n"
    _sentinel, files = I.parse_inspect(out)
    assert files["/big.json"] == content


# ── apply_transforms (logique portail) ────────────────────────────────────────


def test_apply_transforms_creates_and_replaces() -> None:
    meta = _meta_transform()
    result = I.apply_transforms(meta, {"/home/vscode/.claude/settings.json": None})
    data = json.loads(result["/home/vscode/.claude/settings.json"])
    assert data["permissions"] == {"allow": [], "defaultMode": "bypassPermissions"}


def test_apply_transforms_preserves_siblings() -> None:
    meta = _meta_transform()
    current = {"/home/vscode/.claude/settings.json": json.dumps({"keep": 1})}
    data = json.loads(I.apply_transforms(meta, current)["/home/vscode/.claude/settings.json"])
    assert data["keep"] == 1


def test_apply_transforms_remove_only_absent_file_not_created() -> None:
    meta = RecipeMeta(
        id="x",
        type="initialize",
        transform=[{"op": "remove", "target": {"file": "/missing.json", "node": "$.k"}}],
    )
    assert I.apply_transforms(meta, {"/missing.json": None}) == {}


def test_apply_transforms_invalid_json_raises() -> None:
    meta = _meta_transform()
    with pytest.raises(I.InitializerError, match="JSON"):
        I.apply_transforms(meta, {"/home/vscode/.claude/settings.json": "not json {"})


def test_apply_transforms_non_object_root_raises() -> None:
    meta = _meta_transform()
    with pytest.raises(I.InitializerError, match="object"):
        I.apply_transforms(meta, {"/home/vscode/.claude/settings.json": "[1, 2]"})


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


class _FakeSsh:
    """Renvoie des réponses successives et enregistre les commandes reçues."""

    def __init__(self, responses: list[tuple[int, str, str]]) -> None:
        self.responses = list(responses)
        self.commands: list[str] = []

    async def __call__(self, login, ws_id, remote_cmd, *, timeout=60.0):
        self.commands.append(remote_cmd)
        return self.responses.pop(0)


def test_run_initializer_applied(tmp_path: Path, monkeypatch) -> None:
    fake = _FakeSsh(
        [
            (0, _inspect_out(False, {"/home/vscode/.claude/settings.json": None}), ""),
            (0, "__PORTAL_APPLIED__\n", ""),
        ]
    )
    monkeypatch.setattr(I, "run_ssh_capture", fake)
    res = asyncio.run(
        I.run_initializer("alice", "ws1", _meta_transform(), tmp_path, force=False)
    )
    assert res["applied"] is True
    assert res["already_applied"] is False
    assert len(fake.commands) == 2
    # le script d'application contient le contenu transformé (b64)
    apply_script = _decode_remote_script(fake.commands[1])
    assert "bypassPermissions" in base64.b64decode(
        re.findall(r"printf %s '([A-Za-z0-9+/=]+)'", apply_script)[0]
    ).decode("utf-8")


def test_run_initializer_already_applied_short_circuits(tmp_path: Path, monkeypatch) -> None:
    fake = _FakeSsh([(0, _inspect_out(True, {}), "")])
    monkeypatch.setattr(I, "run_ssh_capture", fake)
    res = asyncio.run(
        I.run_initializer("alice", "ws1", _meta_transform(), tmp_path, force=False)
    )
    assert res["already_applied"] is True
    assert len(fake.commands) == 1  # pas d'appel apply


def test_run_initializer_force_reapplies(tmp_path: Path, monkeypatch) -> None:
    fake = _FakeSsh(
        [
            (0, _inspect_out(True, {"/home/vscode/.claude/settings.json": "{}"}), ""),
            (0, "__PORTAL_APPLIED__\n", ""),
        ]
    )
    monkeypatch.setattr(I, "run_ssh_capture", fake)
    res = asyncio.run(
        I.run_initializer("alice", "ws1", _meta_transform(), tmp_path, force=True)
    )
    assert res["applied"] is True
    assert len(fake.commands) == 2


def test_run_initializer_inspect_failure_raises(tmp_path: Path, monkeypatch) -> None:
    fake = _FakeSsh([(255, "", "ssh: connect failed")])
    monkeypatch.setattr(I, "run_ssh_capture", fake)
    with pytest.raises(I.InitializerError, match="connect failed"):
        asyncio.run(
            I.run_initializer("alice", "ws1", _meta_transform(), tmp_path, force=False)
        )


def test_run_initializer_apply_failure_raises(tmp_path: Path, monkeypatch) -> None:
    fake = _FakeSsh(
        [
            (0, _inspect_out(False, {"/home/vscode/.claude/settings.json": None}), ""),
            (1, "", "mv: cannot move"),
        ]
    )
    monkeypatch.setattr(I, "run_ssh_capture", fake)
    with pytest.raises(I.InitializerError, match="cannot move"):
        asyncio.run(
            I.run_initializer("alice", "ws1", _meta_transform(), tmp_path, force=False)
        )
