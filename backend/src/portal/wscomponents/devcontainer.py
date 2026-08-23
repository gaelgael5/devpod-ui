"""Injection des composants système dans un devcontainer.json (spec 18 T1).

Pour chaque composant actif (ordre topologique), écrit sa Feature dans le tmpdir
et fusionne ses contributions dans le contenu du devcontainer :
- `features` : référence la Feature locale `./<name>` ;
- `runArgs` : AJOUTE les args du composant (ex. `--publish`) sans écraser
  l'existant (`--memory`) ;
- `postStartCommand` : chaîne les commandes de démarrage (ex. `sshd`) après
  l'éventuelle commande existante.

Appelé par `devpod/service.py::_write_devcontainer`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .materialize import write_feature
from .models import WorkspaceComponent, render
from .registry import ordered_components


def inject_components(
    content: dict[str, Any],
    tmp_dir: Path,
    ctx: dict[str, str],
    components: list[WorkspaceComponent] | None = None,
) -> None:
    """Injecte les composants système (ou `components`) dans `content` (muté en place)."""
    for comp in ordered_components(components):
        r = render(comp, ctx)
        write_feature(r, tmp_dir)
        content.setdefault("features", {})[f"./{r.name}"] = {}
        if r.run_args:
            content["runArgs"] = [*content.get("runArgs", []), *r.run_args]
        if r.post_start:
            existing = content.get("postStartCommand")
            parts = [existing] if existing else []
            content["postStartCommand"] = " && ".join([*parts, *r.post_start])
