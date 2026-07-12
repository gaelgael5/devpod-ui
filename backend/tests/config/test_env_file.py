"""Tests du writer atomique de fichier .env (config/env_file.py)."""
from __future__ import annotations

import asyncio
import contextlib
import stat
from pathlib import Path

import pytest

import portal.config.env_file as env_file_mod
from portal.config.env_file import update_env_file


@pytest.fixture(autouse=True)
def _fresh_lock():
    """asyncio.Lock se lie à la boucle d'événements de son premier acquire() —
    chaque test pytest-asyncio (mode function-scope) a sa propre boucle, donc le
    verrou module-level doit être recréé à chaque test (non-problème en prod : une
    seule boucle vit pour tout le process)."""
    env_file_mod._lock = asyncio.Lock()


async def test_creates_file_with_keys(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    await update_env_file(target, {"FOO": "bar"})
    assert target.read_text(encoding="utf-8") == "FOO=bar\n"


async def test_updates_existing_key_in_place(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("A=1\nFOO=old\nB=2\n", encoding="utf-8")
    await update_env_file(target, {"FOO": "new"})
    assert target.read_text(encoding="utf-8") == "A=1\nFOO=new\nB=2\n"


async def test_appends_missing_keys(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("A=1\n", encoding="utf-8")
    await update_env_file(target, {"NEW": "x"})
    assert target.read_text(encoding="utf-8") == "A=1\nNEW=x\n"


async def test_preserves_comments_and_blank_lines(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("# commentaire\nA=1\n\nB=2\n", encoding="utf-8")
    await update_env_file(target, {"A": "9"})
    assert target.read_text(encoding="utf-8") == "# commentaire\nA=9\n\nB=2\n"


async def test_doubles_dollar_signs(tmp_path: Path) -> None:
    # docker compose ET bash (dev-deploy.sh `source`) interprètent '$' dans
    # un env_file : un secret contenant '$' doit être échappé en '$$'.
    target = tmp_path / ".env"
    await update_env_file(target, {"SECRET": "a$b$c"})
    assert target.read_text(encoding="utf-8") == "SECRET=a$$b$$c\n"


async def test_sets_restrictive_permissions(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    await update_env_file(target, {"FOO": "bar"})
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600


async def test_multiple_keys_at_once(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("KEEP=1\nOLD=x\n", encoding="utf-8")
    await update_env_file(target, {"OLD": "y", "NEW": "z"})
    assert target.read_text(encoding="utf-8") == "KEEP=1\nOLD=y\nNEW=z\n"


async def test_atomic_write_survives_partial_failure(tmp_path: Path, monkeypatch) -> None:
    # Un crash pendant l'écriture ne doit jamais corrompre le fichier existant.
    target = tmp_path / ".env"
    target.write_text("A=1\n", encoding="utf-8")

    import portal.config.env_file as mod

    def _boom(*a: object, **kw: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(mod.os, "replace", _boom)
    with contextlib.suppress(OSError):
        await update_env_file(target, {"A": "2"})
    assert target.read_text(encoding="utf-8") == "A=1\n"
    # Pas de fichier temporaire résiduel.
    assert list(tmp_path.glob(".tmp-env-*")) == []


# ---------------------------------------------------------------------------
# Bug 035 : deux mises à jour concurrentes de clés distinctes ne doivent jamais
# se perdre mutuellement (read-modify-write sérialisé par un verrou).
# ---------------------------------------------------------------------------


async def test_concurrent_updates_to_distinct_keys_do_not_lose_writes(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("EXISTING=0\n", encoding="utf-8")

    await asyncio.gather(
        update_env_file(target, {"A": "1"}),
        update_env_file(target, {"B": "2"}),
    )

    content = target.read_text(encoding="utf-8")
    assert "A=1" in content
    assert "B=2" in content
    assert "EXISTING=0" in content


async def test_concurrent_updates_are_serialized_not_interleaved(tmp_path, monkeypatch) -> None:
    """Vérifie que le verrou sérialise réellement : le second appel ne commence
    sa lecture qu'après que le premier a fini d'écrire (pas juste "les deux
    résultats finissent par être là par chance")."""
    target = tmp_path / ".env"
    target.write_text("EXISTING=0\n", encoding="utf-8")

    order: list[str] = []
    import portal.config.env_file as mod

    real_sync = mod._update_env_file_sync

    def spy_sync(path, updates):
        order.append(f"start:{list(updates)[0]}")
        real_sync(path, updates)
        order.append(f"end:{list(updates)[0]}")

    monkeypatch.setattr(mod, "_update_env_file_sync", spy_sync)

    await asyncio.gather(
        update_env_file(target, {"A": "1"}),
        update_env_file(target, {"B": "2"}),
    )

    # Un seul writer actif à la fois : pas de "start:B" entre "start:A" et "end:A".
    assert order in (
        ["start:A", "end:A", "start:B", "end:B"],
        ["start:B", "end:B", "start:A", "end:A"],
    )
