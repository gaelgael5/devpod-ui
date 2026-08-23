"""Matérialise un composant rendu en Feature devcontainer locale (spec 18 T1).

Réutilise le mécanisme éprouvé des Features locales de `recipes/` : on écrit un
dossier `<dest>/<name>/` avec `devcontainer-feature.json` + `install.sh`, que
`_write_devcontainer` référence dans `features`. L'install.sh installe les paquets
puis pose les fichiers (contenus en **base64** → robuste à tout contenu :
guillemets, `$`, backticks, marqueurs EOF…). Perms + propriétaire appliqués.

`run_args` et `post_start` du composant ne passent PAS par la Feature : ce sont
des champs devcontainer de haut niveau (`runArgs`, `postStartCommand`), fusionnés
par l'appelant.
"""

from __future__ import annotations

import base64
import json
import shlex
from pathlib import Path

from .models import ComponentRender


def write_feature(rendered: ComponentRender, dest_parent: Path) -> str:
    """Écrit la Feature du composant dans `dest_parent/<name>/`. Retourne son nom."""
    feat = dest_parent / rendered.name
    feat.mkdir(parents=True, exist_ok=True)
    (feat / "devcontainer-feature.json").write_text(
        json.dumps({"id": rendered.name, "version": "1.0.0", "name": rendered.name}, indent=2),
        encoding="utf-8",
    )
    (feat / "install.sh").write_text(_install_script(rendered), encoding="utf-8")
    (feat / "install.sh").chmod(0o755)
    return rendered.name


def _install_script(rendered: ComponentRender) -> str:
    lines = ["#!/bin/sh", "set -e"]
    if rendered.packages:
        pkgs = " ".join(shlex.quote(p) for p in rendered.packages)
        lines += [
            "export DEBIAN_FRONTEND=noninteractive",
            "apt-get update",
            f"apt-get install -y {pkgs}",
        ]
    for f in rendered.files:
        b64 = base64.b64encode(f.content.encode()).decode()
        parent = str(Path(f.path).parent)
        qpath = shlex.quote(f.path)
        lines.append(f"mkdir -p {shlex.quote(parent)}")
        if f.owner:
            # chown du dossier parent (best-effort : l'utilisateur peut ne pas
            # exister au moment du build selon l'image — || true).
            lines.append(f"chown {shlex.quote(f.owner)} {shlex.quote(parent)} 2>/dev/null || true")
        lines.append(f"printf '%s' {shlex.quote(b64)} | base64 -d > {qpath}")
        lines.append(f"chmod {f.mode} {qpath}")
        if f.owner:
            lines.append(f"chown {shlex.quote(f.owner)} {qpath} 2>/dev/null || true")
    return "\n".join(lines) + "\n"
