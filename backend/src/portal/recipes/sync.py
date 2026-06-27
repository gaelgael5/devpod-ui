from __future__ import annotations

import shutil
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

_log = structlog.get_logger(__name__)


def sync_bundled_recipes(bundled_dir: Path, data_recipes_dir: Path) -> None:
    """Synchronise les métadonnées bundlées vers data_recipes_dir.

    recipe.meta.yaml est toujours réécrit depuis la source bundlée (atomique)
    pour garantir que key/version/installs_after restent corrects après une mise
    à jour de l'image Docker. Les autres fichiers du répertoire (scripts, etc.)
    sont copiés seulement s'ils sont absents — les personnalisations admin sont
    ainsi préservées.
    """
    if not bundled_dir.exists():
        _log.debug("bundled_recipes_dir_absent", path=str(bundled_dir))
        return

    data_recipes_dir.mkdir(parents=True, exist_ok=True)

    for entry in sorted(bundled_dir.iterdir()):
        if not entry.is_dir() or not (entry / "recipe.meta.yaml").exists():
            continue
        dest = data_recipes_dir / entry.name
        dest.mkdir(parents=True, exist_ok=True)

        # Toujours mettre à jour recipe.meta.yaml depuis la source bundlée
        # pour que key/version/installs_after soient toujours corrects.
        src_meta = entry / "recipe.meta.yaml"
        dest_meta = dest / "recipe.meta.yaml"
        tmp_meta = dest / ".tmp-recipe.meta.yaml"
        shutil.copy2(src_meta, tmp_meta)
        tmp_meta.rename(dest_meta)
        _log.debug("recipe_meta_updated", recipe_id=entry.name)

        # Copier les autres fichiers seulement s'ils sont absents.
        for src_file in entry.iterdir():
            if src_file.name == "recipe.meta.yaml":
                continue
            dest_file = dest / src_file.name
            if not dest_file.exists():
                shutil.copy2(src_file, dest_file)
                _log.debug(
                    "recipe_file_synced",
                    recipe_id=entry.name,
                    file=src_file.name,
                )


async def sync_recipes_to_db(
    data_recipes_dir: Path, conn: AsyncConnection, *, login: str | None = None
) -> None:
    """Synchronise les métadonnées des recipes filesystem → DB. Idempotent."""
    from ..db.recipes import load_recipes_from_dir_to_db

    scope = "user" if login else "shared"
    await load_recipes_from_dir_to_db(data_recipes_dir, scope, login, conn)
