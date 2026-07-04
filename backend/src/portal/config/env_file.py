"""Écriture atomique de clés dans un fichier `.env` (KEY=VALUE par ligne)."""
from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
from pathlib import Path

# Un seul fichier .env par portail (_data_root()/.env) : un verrou global suffit à
# sérialiser les cycles read-modify-write. Sans lui, deux mises à jour concurrentes
# de clés distinctes se lisent la même version du fichier et la dernière à écrire
# écrase (perd) la mise à jour de l'autre (bug 035).
_lock = asyncio.Lock()


def _update_env_file_sync(path: Path, updates: dict[str, str]) -> None:
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


async def update_env_file(path: Path, updates: dict[str, str]) -> None:
    """Met à jour (ou ajoute) des clés dans un fichier .env, atomiquement et sérialisé.

    Préserve les lignes non concernées (autres clés, commentaires, lignes vides,
    ordre). tempfile dans le même dossier + os.replace : un crash en cours
    d'écriture ne corrompt jamais le fichier existant (§ État fichiers).

    Le cycle lecture→modification→écriture est sérialisé par un verrou module-level
    (bug 035) : deux appels concurrents ne peuvent jamais lire la même version du
    fichier et se perdre mutuellement. L'I/O bloquante est déportée via
    asyncio.to_thread (jamais dans l'event loop d'un handler async).

    Les `$` des valeurs sont doublés en `$$` : ce fichier est à la fois `source`-é
    par bash (dev-deploy.sh) et lu comme `env_file` par docker compose, qui
    interprètent tous deux `$` — même convention que LOCAL_PASSWORD_HASH.
    """
    async with _lock:
        await asyncio.to_thread(_update_env_file_sync, path, updates)
