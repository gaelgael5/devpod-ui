"""Arborescence agent-config d'un workspace (spec 35 §4.2).

Layout : {root}/{ws_id}/{agent_id}/{filename} — dossiers 700, fichiers 600.

Le répertoire {ws_id} est la source d'un bind mount vers le conteneur : il ne
doit JAMAIS être supprimé/recréé pendant la vie du workspace (le mount resterait
épinglé sur l'ancien inode et les mises à jour à chaud deviendraient invisibles).
On remplace atomiquement les fichiers À L'INTÉRIEUR (tempfile + os.replace) et on
retire les sous-répertoires d'agents devenus obsolètes.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .models import AGENT_ID_RE, validate_filename
from .renderer import AgentRenderError, render_agent_file

# ws_id = "{login}-{name}" (login: [a-z0-9._-], name: [a-z0-9-]).
WS_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")


class AgentTreeError(Exception):
    pass


def _validated_ws_dir(root: Path, ws_id: str) -> Path:
    if not WS_ID_RE.fullmatch(ws_id) or ".." in ws_id:
        raise AgentTreeError(f"ws_id invalide : {ws_id!r}")
    ws_dir = root / ws_id
    if not ws_dir.is_relative_to(root):
        raise AgentTreeError(f"chemin hors racine : {ws_dir!r}")
    return ws_dir


def generate_workspace_tree(
    root: Path,
    ws_id: str,
    agent_types: list[dict[str, Any]],
    context: dict[str, Any],
) -> Path:
    """(Re)génère l'arborescence du workspace et retourne son répertoire.

    Tout le rendu est fait AVANT de toucher au disque : un template cassé ne
    corrompt jamais les fichiers existants.
    """
    ws_dir = _validated_ws_dir(root, ws_id)

    rendered: list[tuple[str, str, str]] = []  # (agent_id, filename, contenu)
    for agent in agent_types:
        agent_id, filename = str(agent["id"]), str(agent["filename"])
        if not AGENT_ID_RE.fullmatch(agent_id):
            raise AgentTreeError(f"agent id invalide : {agent_id!r}")
        try:
            validate_filename(filename)
        except ValueError as exc:
            raise AgentTreeError(str(exc)) from exc
        try:
            content = render_agent_file(str(agent["template"]), context)
        except AgentRenderError as exc:
            raise AgentTreeError(f"agent '{agent_id}' : {exc}") from exc
        rendered.append((agent_id, filename, content))

    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    ws_dir.mkdir(exist_ok=True)
    os.chmod(ws_dir, 0o700)

    for agent_id, filename, content in rendered:
        agent_dir = ws_dir / agent_id
        agent_dir.mkdir(exist_ok=True)
        os.chmod(agent_dir, 0o700)
        _atomic_write(agent_dir / filename, content)

    expected = {agent_id for agent_id, _, _ in rendered}
    for entry in ws_dir.iterdir():
        if entry.name not in expected:
            shutil.rmtree(entry) if entry.is_dir() else entry.unlink()

    return ws_dir


def _atomic_write(path: Path, content: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
