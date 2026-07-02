"""Tests du writer atomique de fichier .env (config/env_file.py)."""
from __future__ import annotations

import contextlib
import stat
from pathlib import Path

from portal.config.env_file import update_env_file


def test_creates_file_with_keys(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    update_env_file(target, {"FOO": "bar"})
    assert target.read_text(encoding="utf-8") == "FOO=bar\n"


def test_updates_existing_key_in_place(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("A=1\nFOO=old\nB=2\n", encoding="utf-8")
    update_env_file(target, {"FOO": "new"})
    assert target.read_text(encoding="utf-8") == "A=1\nFOO=new\nB=2\n"


def test_appends_missing_keys(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("A=1\n", encoding="utf-8")
    update_env_file(target, {"NEW": "x"})
    assert target.read_text(encoding="utf-8") == "A=1\nNEW=x\n"


def test_preserves_comments_and_blank_lines(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("# commentaire\nA=1\n\nB=2\n", encoding="utf-8")
    update_env_file(target, {"A": "9"})
    assert target.read_text(encoding="utf-8") == "# commentaire\nA=9\n\nB=2\n"


def test_doubles_dollar_signs(tmp_path: Path) -> None:
    # docker compose ET bash (dev-deploy.sh `source`) interprètent '$' dans
    # un env_file : un secret contenant '$' doit être échappé en '$$'.
    target = tmp_path / ".env"
    update_env_file(target, {"SECRET": "a$b$c"})
    assert target.read_text(encoding="utf-8") == "SECRET=a$$b$$c\n"


def test_sets_restrictive_permissions(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    update_env_file(target, {"FOO": "bar"})
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600


def test_multiple_keys_at_once(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("KEEP=1\nOLD=x\n", encoding="utf-8")
    update_env_file(target, {"OLD": "y", "NEW": "z"})
    assert target.read_text(encoding="utf-8") == "KEEP=1\nOLD=y\nNEW=z\n"


def test_atomic_write_survives_partial_failure(tmp_path: Path, monkeypatch) -> None:
    # Un crash pendant l'écriture ne doit jamais corrompre le fichier existant.
    target = tmp_path / ".env"
    target.write_text("A=1\n", encoding="utf-8")

    import portal.config.env_file as mod

    def _boom(*a: object, **kw: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(mod.os, "replace", _boom)
    with contextlib.suppress(OSError):
        update_env_file(target, {"A": "2"})
    assert target.read_text(encoding="utf-8") == "A=1\n"
    # Pas de fichier temporaire résiduel.
    assert list(tmp_path.glob(".tmp-env-*")) == []
