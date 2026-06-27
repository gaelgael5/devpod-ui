"""Confinement des chemins workspace (spec 24 I-5).

Tout chemin est relatif à la racine `/workspaces/{name}`, normalisé côté portail.
Rejet de `..`, des chemins absolus et des composantes hors racine.
"""
from __future__ import annotations

import posixpath

from .errors import DevpodToolError


def safe_workspace_path(workspace: str, path: str) -> str:
    """Retourne le chemin absolu confiné sous `/workspaces/{workspace}`.

    Lève `DevpodToolError` si le chemin est absolu, contient un NUL, ou s'évade de
    la racine après normalisation (résolution des `..`).
    """
    if path.startswith("/") or "\0" in path:
        raise DevpodToolError("chemin absolu interdit")
    root = f"/workspaces/{workspace}"
    resolved = posixpath.normpath(posixpath.join(root, path or "."))
    if resolved != root and not resolved.startswith(root + "/"):
        raise DevpodToolError("chemin hors du workspace")
    return resolved
