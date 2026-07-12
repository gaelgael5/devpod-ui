"""Exécution des recipes `type: initialize` dans le conteneur d'un workspace.

Aucune dépendance côté conteneur au-delà de sh/coreutils (cat, base64, tar,
cp, mv) : la logique JSON (transform) est appliquée CÔTÉ PORTAIL (init_ops.py).
Deux appels SSH :
  1. inspection — présence de la sentinelle + contenu des fichiers `transform` ;
  2. application — extraction des `copy`, écriture des fichiers transformés
     (tmp + mv dans le dossier cible), pose de la sentinelle.
"""

from __future__ import annotations

import base64
import io
import json
import shlex
import tarfile
from pathlib import Path
from typing import Any

import structlog

from ..config.store import _data_root, safe_user_path
from ..devpod.ssh_exec import run_ssh_capture
from .init_ops import apply_remove, apply_replace, sentinel_location
from .models import RecipeMeta

_log = structlog.get_logger(__name__)

_MARK_SENTINEL = "__PORTAL_SENTINEL__"
_MARK_FILE = "__PORTAL_FILE__"
_MARK_EOF = "__PORTAL_EOF__"
_MARK_APPLIED = "__PORTAL_APPLIED__"


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
    """Sérialise les ops de la recipe (structure commune sentinelle/inspection)."""
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


def _sentinel_exprs(spec: dict[str, Any], recipe_dir: Path | None) -> tuple[str, str]:
    """Expressions sh (fichier sentinelle, dossier parent) — gère le cas $HOME."""
    copies = spec.get("copy") or []
    src_is_file = bool(
        copies and recipe_dir is not None and (recipe_dir / copies[0]["source"]).is_file()
    )
    base, rel = sentinel_location(spec, first_copy_source_is_file=src_is_file)
    if base is None:
        return '"$HOME"/' + shlex.quote(rel), '"$HOME"/' + shlex.quote(".portal")
    return shlex.quote(f"{base}/{rel}"), shlex.quote(f"{base}/.portal")


def _wrap_b64(script: str) -> str:
    """Encode le script pour transport SSH sans hasard de quoting."""
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    return f"bash -c \"$(printf %s '{b64}' | base64 -d)\""


def build_inspect_cmd(meta: RecipeMeta, recipe_dir: Path | None) -> str:
    """Script d'inspection : sentinelle + contenu (b64) des fichiers transform."""
    spec = build_spec(meta)
    sentinel, _ = _sentinel_exprs(spec, recipe_dir)
    lines = [
        "set -e",
        f'if [ -e {sentinel} ]; then echo "{_MARK_SENTINEL} 1"; '
        f'else echo "{_MARK_SENTINEL} 0"; fi',
    ]
    for file in _transform_files(meta):
        path_b64 = base64.b64encode(file.encode("utf-8")).decode("ascii")
        q = shlex.quote(file)
        lines += [
            f'echo "{_MARK_FILE} {path_b64}"',
            f"if [ -f {q} ]; then base64 < {q}; fi",
            f'echo "{_MARK_EOF}"',
        ]
    return _wrap_b64("\n".join(lines) + "\n")


def _transform_files(meta: RecipeMeta) -> list[str]:
    """Fichiers cibles des transforms, dédupliqués, ordre d'apparition."""
    seen: list[str] = []
    for tr in meta.transform:
        if tr.target.file not in seen:
            seen.append(tr.target.file)
    return seen


def parse_inspect(out: str) -> tuple[bool, dict[str, str | None]]:
    """Décode la sortie d'inspection → (sentinel_exists, {fichier: contenu|None})."""
    sentinel_exists = False
    files: dict[str, str | None] = {}
    current: str | None = None
    chunks: list[str] = []
    for line in out.splitlines():
        if line.startswith(_MARK_SENTINEL):
            sentinel_exists = line.split()[-1] == "1"
        elif line.startswith(_MARK_FILE):
            current = base64.b64decode(line.split()[-1]).decode("utf-8")
            chunks = []
        elif line.startswith(_MARK_EOF):
            if current is not None:
                raw = "".join(chunks)
                files[current] = (
                    base64.b64decode(raw).decode("utf-8", errors="replace") if raw else None
                )
            current = None
        elif current is not None:
            chunks.append(line.strip())
    return sentinel_exists, files


def apply_transforms(meta: RecipeMeta, current: dict[str, str | None]) -> dict[str, str]:
    """Applique les ops côté portail. Retourne {fichier: nouveau contenu JSON}.

    Un fichier absent dont toutes les ops sont des `remove` n'est pas créé
    (même sémantique que l'ancien moteur embarqué).
    """
    roots: dict[str, dict[str, Any]] = {}
    existed: dict[str, bool] = {}
    for tr in meta.transform:
        file = tr.target.file
        if file not in roots:
            raw = current.get(file)
            existed[file] = raw is not None
            if raw is None or not raw.strip():
                roots[file] = {}
            else:
                try:
                    parsed = json.loads(raw)
                except ValueError as exc:
                    raise InitializerError(f"{file}: JSON invalide: {exc}") from exc
                if not isinstance(parsed, dict):
                    raise InitializerError(f"{file}: root JSON is not an object")
                roots[file] = parsed
        if tr.op == "replace":
            apply_replace(roots[file], tr.target.node, tr.value)
        elif tr.op == "remove":
            apply_remove(roots[file], tr.target.node)
        else:  # défense en profondeur — le modèle pydantic l'interdit déjà
            raise InitializerError(f"unknown transform op: {tr.op!r}")
    return {
        file: json.dumps(root, indent=2, ensure_ascii=False) + "\n"
        for file, root in roots.items()
        if existed[file] or root  # ne pas créer un fichier vide via remove-only
    }


def build_apply_cmd(
    meta: RecipeMeta, recipe_dir: Path, new_files: dict[str, str]
) -> str:
    """Script d'application : copies, fichiers transformés (tmp+mv), sentinelle."""
    spec = build_spec(meta)
    sentinel, sentinel_dir = _sentinel_exprs(spec, recipe_dir)
    lines = ["set -e", 'D=$(mktemp -d)', "trap 'rm -rf \"$D\"' EXIT"]

    if meta.copies:
        tar_b64 = _tar_recipe_sources(recipe_dir)
        lines += [
            'mkdir -p "$D/src"',
            f"printf %s '{tar_b64}' | base64 -d | tar -xzf - -C \"$D/src\"",
        ]
        for c in meta.copies:
            src = '"$D/src/"' + shlex.quote(c.source)
            target = shlex.quote(c.target)
            if (recipe_dir / c.source).is_dir():
                lines += [f"mkdir -p {target}", f"cp -a {src}/. {target}/"]
            else:
                parent = shlex.quote(str(Path(c.target).parent))
                lines += [f"mkdir -p {parent}", f"cp -a {src} {target}"]

    for idx, (file, content) in enumerate(new_files.items()):
        content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        parent = shlex.quote(str(Path(file).parent))
        tmp = shlex.quote(f"{file}.portal-tmp")
        lines += [
            f"mkdir -p {parent}",
            f"printf %s '{content_b64}' | base64 -d > {tmp}  # transform {idx}",
            f"mv {tmp} {shlex.quote(file)}",
        ]

    lines += [f"mkdir -p {sentinel_dir}", f": > {sentinel}", f'echo "{_MARK_APPLIED}"']
    return _wrap_b64("\n".join(lines) + "\n")


async def run_initializer(
    login: str, ws_name: str, meta: RecipeMeta, recipe_dir: Path, *, force: bool
) -> dict[str, Any]:
    """Exécute l'action et retourne {applied, already_applied, log}."""
    ws_id = f"{login}-{ws_name}"

    rc, out, err = await run_ssh_capture(login, ws_id, build_inspect_cmd(meta, recipe_dir))
    if rc != 0:
        _log.warning("initializer_inspect_failed", ws_id=ws_id, recipe=meta.id, rc=rc)
        raise InitializerError((out + err).strip() or f"inspection failed (exit {rc})")
    sentinel_exists, current = parse_inspect(out)

    if sentinel_exists and not force:
        _log.info("initializer_run", ws_id=ws_id, recipe=meta.id, already_applied=True)
        return {"applied": False, "already_applied": True, "log": "already applied (sentinel)"}

    new_files = apply_transforms(meta, current)
    rc, out, err = await run_ssh_capture(
        login, ws_id, build_apply_cmd(meta, recipe_dir, new_files)
    )
    log = (out + err).strip()
    if rc != 0 or _MARK_APPLIED not in out:
        _log.warning("initializer_apply_failed", ws_id=ws_id, recipe=meta.id, rc=rc)
        raise InitializerError(log or f"apply failed (exit {rc})")

    _log.info("initializer_run", ws_id=ws_id, recipe=meta.id, applied=True, force=force)
    return {"applied": True, "already_applied": False, "log": log}
