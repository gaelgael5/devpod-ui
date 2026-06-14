from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path

import structlog
import yaml

from .models import RecipeMeta

_log = structlog.get_logger(__name__)


class CycleError(ValueError):
    """Dépendance circulaire détectée dans installs_after."""


class RecipeNotFoundError(KeyError):
    """Recette demandée introuvable dans le registre disponible."""


class RecipeRegistry:
    def __init__(
        self,
        builtin_dir: Path | None = None,
        shared_dir: Path | None = None,
    ) -> None:
        self._builtin_dir: Path | None = builtin_dir
        self._shared_dir: Path | None = shared_dir

    def load_shared(self) -> dict[str, RecipeMeta]:
        """Charge builtin puis partagées admin (partagées écrasent builtin à id égal)."""
        recipes: dict[str, RecipeMeta] = {}
        for directory in (self._builtin_dir, self._shared_dir):
            if directory is not None:
                recipes.update(self.load_dir(directory))
        return recipes

    def load_dir(self, directory: Path) -> dict[str, RecipeMeta]:
        """Charge toutes les recettes valides depuis un répertoire (non-récursif)."""
        recipes: dict[str, RecipeMeta] = {}
        if not directory.exists():
            return recipes
        for entry in sorted(directory.iterdir()):
            if entry.is_dir():
                meta = self._load_meta(entry)
                if meta is not None:
                    recipes[meta.id] = meta
        return recipes

    def resolve_order(
        self,
        selected_ids: list[str],
        available: dict[str, RecipeMeta],
    ) -> list[RecipeMeta]:
        """Tri topologique Kahn sur installs_after.

        Lève RecipeNotFoundError si un id est inconnu.
        Lève CycleError si un cycle est détecté.
        """
        for rid in selected_ids:
            if rid not in available:
                raise RecipeNotFoundError(f"Recipe {rid!r} introuvable dans le registre")

        if len(selected_ids) != len(set(selected_ids)):
            raise ValueError(
                f"selected_ids contient des doublons : {selected_ids}"
            )

        selected_set = set(selected_ids)
        in_degree: dict[str, int] = {rid: 0 for rid in selected_ids}
        dependents: defaultdict[str, list[str]] = defaultdict(list)

        for rid in selected_ids:
            for dep in available[rid].installs_after:
                if dep in selected_set:
                    in_degree[rid] += 1
                    dependents[dep].append(rid)

        queue: deque[str] = deque(rid for rid in selected_ids if in_degree[rid] == 0)
        result: list[RecipeMeta] = []

        while queue:
            rid = queue.popleft()
            result.append(available[rid])
            for dependent in sorted(dependents[rid]):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(result) != len(selected_ids):
            raise CycleError(f"Cycle détecté dans installs_after parmi : {selected_ids}")

        return result

    @staticmethod
    def _load_meta(recipe_dir: Path) -> RecipeMeta | None:
        meta_file = recipe_dir / "recipe.meta.yaml"
        if not meta_file.exists():
            return None
        try:
            data: object = yaml.safe_load(meta_file.read_text(encoding="utf-8"))
            return RecipeMeta.model_validate(data)
        except Exception as exc:
            _log.warning(
                "recipe_meta_invalid",
                path=str(meta_file),
                error=str(exc),
            )
            return None
