"""Exécution des recipes `type: initialize` dans le conteneur d'un workspace.

Le moteur (`_init_runner.py`) et les opérations sont poussés via SSH (base64) puis
exécutés au runtime, volumes montés. Les ops sont lues depuis le `recipe.meta.yaml`
sur disque (la DB ne les persiste pas), comme `start.sh` pour les recipes `start`.
"""

from __future__ import annotations

import base64
import io
import json
import tarfile
from pathlib import Path
from typing import Any

import structlog

from ..config.store import _data_root, safe_user_path
from ..devpod.ssh_exec import run_ssh_capture
from .models import RecipeMeta

_log = structlog.get_logger(__name__)

_RUNNER_PATH = Path(__file__).with_name("_init_runner.py")


class InitializerError(RuntimeError):
    """Erreur d'exécution d'une action initialize."""


def locate_recipe_dir(login: str, recipe_id: str) -> Path | None:
    """Localise le dossier d'une recipe (perso prioritaire), avec garde traversal."""
    personal = safe_user_path(login, "recipes")
    shared = _data_root() / "recipes"
    for base in (personal, shared):
        cand = base / recipe_id
        if cand.exists() and cand.is_relative_to(base):
            return cand
    return None


def build_spec(meta: RecipeMeta) -> dict[str, Any]:
    """Sérialise les ops de la recipe pour le moteur (stdin JSON)."""
    transforms: list[dict[str, Any]] = []
    for tr in meta.transform:
        entry: dict[str, Any] = {
            "op": tr.op,
            "target": {"file": tr.target.file, "node": tr.target.node},
        }
        if tr.op == "replace":
            entry["value"] = tr.value
        transforms.append(entry)
    return {
        "recipe_id": meta.id,
        "version": meta.version,
        "copy": [{"source": c.source, "target": c.target} for c in meta.copies],
        "transform": transforms,
    }


def _tar_recipe_sources(recipe_dir: Path) -> str:
    """tar.gz (base64) du contenu de la recipe — `files/...` résolu à l'extraction."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for item in sorted(recipe_dir.iterdir()):
            tar.add(item, arcname=item.name)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def build_remote_cmd(meta: RecipeMeta, recipe_dir: Path, *, force: bool) -> str:
    """Construit la commande SSH distante (un script bash encodé base64)."""
    runner_b64 = base64.b64encode(_RUNNER_PATH.read_bytes()).decode("ascii")
    ops_b64 = base64.b64encode(json.dumps(build_spec(meta)).encode("utf-8")).decode("ascii")

    flags = ["--force"] if force else []
    extract = ""
    if meta.copies:
        tar_b64 = _tar_recipe_sources(recipe_dir)
        extract = (
            f'mkdir -p "$D/src"\nprintf %s \'{tar_b64}\' | base64 -d | tar -xzf - -C "$D/src"\n'
        )
        flags += ["--src", '"$D/src"']

    flags_str = " ".join(flags)
    script = (
        "set +e\n"
        "if ! command -v python3 >/dev/null 2>&1; then\n"
        '  echo \'{"applied": false, "already_applied": false,'
        ' "error": "python3 not found in container"}\'\n'
        "  exit 1\n"
        "fi\n"
        "D=$(mktemp -d)\n"
        f"printf %s '{runner_b64}' | base64 -d > \"$D/r.py\"\n"
        f"{extract}"
        f"printf %s '{ops_b64}' | base64 -d | python3 \"$D/r.py\" {flags_str}\n"
        "RC=$?\n"
        'rm -rf "$D"\n'
        "exit $RC\n"
    )
    # base64 ne contient jamais de quote simple → quotes explicites sûres.
    script_b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    return f"bash -c \"$(printf %s '{script_b64}' | base64 -d)\""


def _parse_result(stdout: str) -> dict[str, Any] | None:
    """Extrait la dernière ligne JSON produite par le moteur."""
    for line in reversed([ln for ln in stdout.splitlines() if ln.strip()]):
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and (
            "applied" in obj or "already_applied" in obj or "error" in obj
        ):
            return obj
    return None


async def run_initializer(
    login: str, ws_name: str, meta: RecipeMeta, recipe_dir: Path, *, force: bool
) -> dict[str, Any]:
    """Exécute l'action et retourne {applied, already_applied, log}."""
    ws_id = f"{login}-{ws_name}"
    remote_cmd = build_remote_cmd(meta, recipe_dir, force=force)
    rc, out, err = await run_ssh_capture(login, ws_id, remote_cmd)
    log = (out + err).strip()
    result = _parse_result(out)

    if result is None:
        _log.warning("initializer_no_result", ws_id=ws_id, recipe=meta.id, rc=rc)
        raise InitializerError(log or f"no result from runner (exit {rc})")
    if result.get("error"):
        raise InitializerError(str(result["error"]))

    _log.info(
        "initializer_run",
        ws_id=ws_id,
        recipe=meta.id,
        applied=result.get("applied"),
        already_applied=result.get("already_applied"),
        force=force,
    )
    return {
        "applied": bool(result.get("applied")),
        "already_applied": bool(result.get("already_applied")),
        "log": log,
    }
