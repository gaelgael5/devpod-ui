from __future__ import annotations

import shutil
from pathlib import Path

import structlog

_log = structlog.get_logger(__name__)


def sync_bundled_recipes(bundled_dir: Path, data_recipes_dir: Path) -> None:
    """Copie les recettes du répertoire bundlé vers data_recipes_dir si absentes.

    Idempotent : ne jamais écraser une recette déjà présente — l'admin peut
    l'avoir personnalisée. Toute recette dotée d'un recipe.meta.yaml est éligible.
    """
    if not bundled_dir.exists():
        _log.debug("bundled_recipes_dir_absent", path=str(bundled_dir))
        return

    data_recipes_dir.mkdir(parents=True, exist_ok=True)

    for entry in sorted(bundled_dir.iterdir()):
        if not entry.is_dir() or not (entry / "recipe.meta.yaml").exists():
            continue
        dest = data_recipes_dir / entry.name
        if dest.exists():
            _log.debug("recipe_already_present", recipe_id=entry.name)
            continue
        tmp = data_recipes_dir / f".tmp-sync-{entry.name}"
        try:
            shutil.copytree(entry, tmp, copy_function=shutil.copy2)
            tmp.rename(dest)
            _log.info("recipe_synced", recipe_id=entry.name)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
