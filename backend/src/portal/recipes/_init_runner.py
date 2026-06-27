#!/usr/bin/env python3
"""Moteur d'initialisation des recipes `type: initialize`.

Ce module est **autonome** (stdlib uniquement) : il est importé tel quel par les
tests du portail ET transmis encodé en base64 puis exécuté dans le conteneur du
workspace (`python3 _init_runner.py`). Il ne doit donc jamais importer `portal.*`.

Entrée (stdin, JSON) :
    {"recipe_id": str, "version": str,
     "copy": [{"source": str, "target": str}],
     "transform": [{"op": "replace"|"remove",
                    "target": {"file": str, "node": "$.a.b"},
                    "value": <any>}]}

Argv : [--src <dir>] [--force]
Sortie (stdout) : une ligne JSON {"applied", "already_applied", "message"}.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


def _split_node(node: str) -> list[str]:
    """'$.a.b' -> ['a', 'b']. Suppose un dot-path déjà validé en amont."""
    if not node.startswith("$."):
        raise ValueError(f"invalid node path: {node!r}")
    return node[2:].split(".")


def _load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        with _suppress():
            os.unlink(tmp_name)
        raise


class _suppress:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: object) -> bool:
        return True


def apply_replace(file: Path, node: str, value: Any) -> None:
    keys = _split_node(node)
    root = _load_json(file)
    if not isinstance(root, dict):
        raise ValueError(f"{file}: root JSON is not an object")
    cur = root
    for k in keys[:-1]:
        nxt = cur.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[k] = nxt
        cur = nxt
    cur[keys[-1]] = value
    _atomic_write_json(file, root)


def apply_remove(file: Path, node: str) -> None:
    keys = _split_node(node)
    if not file.exists():
        return
    root = _load_json(file)
    if not isinstance(root, dict):
        return
    cur: Any = root
    for k in keys[:-1]:
        if not isinstance(cur, dict) or k not in cur:
            return
        cur = cur[k]
    if isinstance(cur, dict) and keys[-1] in cur:
        del cur[keys[-1]]
        _atomic_write_json(file, root)


def apply_copy(src_root: Path, source: str, target: Path) -> None:
    src = src_root / source
    if not src.exists():
        raise FileNotFoundError(f"copy source not found: {src}")
    if src.is_dir():
        shutil.copytree(src, target, dirs_exist_ok=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)


def sentinel_path(spec: dict[str, Any], src_root: str | None = None) -> Path:
    """Déduit l'emplacement du témoin : <dir cible>/.portal/<id>@<version>.

    On privilégie le dossier parent de la première cible `transform` (un fichier),
    sinon le dossier cible de la première `copy` (un dossier) — ou son parent si la
    source copiée est un simple fichier.
    """
    transforms = spec.get("transform") or []
    copies = spec.get("copy") or []
    if transforms:
        base = Path(transforms[0]["target"]["file"]).parent
    elif copies:
        target = Path(copies[0]["target"])
        source = copies[0]["source"]
        if src_root is not None and (Path(src_root) / source).is_file():
            base = target.parent
        else:
            base = target
    else:
        raise ValueError("recipe initialize without any copy/transform op")
    name = f"{spec['recipe_id']}@{spec['version']}"
    return base / ".portal" / name


def run(spec: dict[str, Any], *, src_root: str | None, force: bool) -> dict[str, Any]:
    sentinel = sentinel_path(spec, src_root)
    if sentinel.exists() and not force:
        return {
            "applied": False,
            "already_applied": True,
            "message": f"already applied (sentinel {sentinel})",
        }

    for c in spec.get("copy") or []:
        if src_root is None:
            raise ValueError("copy op requires a source root (--src)")
        apply_copy(Path(src_root), c["source"], Path(c["target"]))

    for tr in spec.get("transform") or []:
        file = Path(tr["target"]["file"])
        node = tr["target"]["node"]
        if tr["op"] == "replace":
            apply_replace(file, node, tr["value"])
        elif tr["op"] == "remove":
            apply_remove(file, node)
        else:
            raise ValueError(f"unknown transform op: {tr['op']!r}")

    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("", encoding="utf-8")
    return {"applied": True, "already_applied": False, "message": "applied"}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    force = "--force" in args
    src_root: str | None = None
    if "--src" in args:
        src_root = args[args.index("--src") + 1]

    spec = json.load(sys.stdin)
    try:
        result = run(spec, src_root=src_root, force=force)
    except Exception as exc:  # noqa: BLE001 — surface l'erreur au backend
        print(json.dumps({"applied": False, "already_applied": False, "error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
