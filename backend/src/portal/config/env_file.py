"""Écriture atomique de clés dans un fichier `.env` (KEY=VALUE par ligne)."""
from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


def update_env_file(path: Path, updates: dict[str, str]) -> None:
    """Met à jour (ou ajoute) des clés dans un fichier .env, atomiquement.

    Préserve les lignes non concernées (autres clés, commentaires, lignes vides,
    ordre). tempfile dans le même dossier + os.replace : un crash en cours
    d'écriture ne corrompt jamais le fichier existant (§ État fichiers).

    Les `$` des valeurs sont doublés en `$$` : ce fichier est à la fois `source`-é
    par bash (dev-deploy.sh) et lu comme `env_file` par docker compose, qui
    interprètent tous deux `$` — même convention que LOCAL_PASSWORD_HASH.
    """
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0]
            if key in remaining:
                out.append(f"{key}={remaining.pop(key).replace('$', '$$')}")
                continue
        out.append(line)
    for key, value in remaining.items():
        out.append(f"{key}={value.replace('$', '$$')}")

    content = "\n".join(out) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-env-")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
