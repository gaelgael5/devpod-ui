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


class DependencyNotFoundError(KeyError):
    """GUID de dépendance introuvable dans le registre."""


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

    @staticmethod
    def build_key_index(available: dict[str, RecipeMeta]) -> dict[str, RecipeMeta]:
        """Construit un index key (GUID) → RecipeMeta depuis un dict id → RecipeMeta."""
        return {m.key: m for m in available.values()}

    def expand_with_deps(
        self,
        selected_ids: list[str],
        available: dict[str, RecipeMeta],
    ) -> list[str]:
        """Étend la liste des IDs sélectionnés avec leurs dépendances transitives.

        Résout récursivement les `installs_after` (GUIDs) de chaque recipe sélectionnée
        et des dépendances elles-mêmes. Les dépendances auto-ajoutées s'intercalent avant
        la recipe qui en dépend.

        Lève RecipeNotFoundError si un id sélectionné est inconnu.
        Lève DependencyNotFoundError si un GUID de dépendance est introuvable.
        """
        for rid in selected_ids:
            if rid not in available:
                raise RecipeNotFoundError(f"Recipe {rid!r} introuvable dans le registre")

        key_index = self.build_key_index(available)

        # BFS : on part des sélectionnés, on ajoute les dépendances en tête
        seen_keys: set[str] = set()
        result_ids: list[str] = []

        def _visit(recipe: RecipeMeta) -> None:
            if recipe.key in seen_keys:
                return
            seen_keys.add(recipe.key)
            for dep_key in recipe.installs_after:
                dep = key_index.get(dep_key)
                if dep is None:
                    raise DependencyNotFoundError(
                        f"Recipe {recipe.id!r} dépend du GUID {dep_key!r}"
                        " introuvable dans le registre"
                    )
                _visit(dep)
            result_ids.append(recipe.id)

        for rid in selected_ids:
            _visit(available[rid])

        return result_ids

    def resolve_order(
        self,
        selected_ids: list[str],
        available: dict[str, RecipeMeta],
    ) -> list[RecipeMeta]:
        """Tri topologique Kahn sur installs_after (GUIDs).

        Lève RecipeNotFoundError si un id est inconnu.
        Lève CycleError si un cycle est détecté.
        Lève DependencyNotFoundError si un GUID de dépendance est introuvable.

        Note : appeler expand_with_deps avant pour inclure les dépendances transitives.
        """
        for rid in selected_ids:
            if rid not in available:
                raise RecipeNotFoundError(f"Recipe {rid!r} introuvable dans le registre")

        if len(selected_ids) != len(set(selected_ids)):
            raise ValueError(f"selected_ids contient des doublons : {selected_ids}")

        key_index = self.build_key_index(available)
        selected_set = set(selected_ids)

        in_degree: dict[str, int] = {rid: 0 for rid in selected_ids}
        dependents: defaultdict[str, list[str]] = defaultdict(list)

        for rid in selected_ids:
            recipe = available[rid]
            for dep_key in recipe.installs_after:
                dep = key_index.get(dep_key)
                if dep is None:
                    raise DependencyNotFoundError(
                        f"Recipe {rid!r} dépend du GUID {dep_key!r} introuvable"
                    )
                if dep.id in selected_set:
                    in_degree[rid] += 1
                    dependents[dep.id].append(rid)

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
    def filter_by_type(
        recipes: dict[str, RecipeMeta],
        type_filter: str,
    ) -> dict[str, RecipeMeta]:
        """Retourne les recettes dont le champ `type` correspond à `type_filter`."""
        return {k: v for k, v in recipes.items() if v.type == type_filter}

    @staticmethod
    def _load_meta(recipe_dir: Path) -> RecipeMeta | None:
        meta_file = recipe_dir / "recipe.meta.yaml"
        if not meta_file.exists():
            return None
        try:
            data: object = yaml.safe_load(meta_file.read_text(encoding="utf-8"))
            meta = RecipeMeta.model_validate(data)
        except Exception as exc:
            _log.warning(
                "recipe_meta_invalid",
                path=str(meta_file),
                error=str(exc),
            )
            return None
        if meta.type == "start":
            if not (recipe_dir / "start.sh").exists():
                _log.warning("recipe_start_missing_start_sh", path=str(recipe_dir))
                return None
            if (recipe_dir / "devcontainer-feature.json").exists():
                _log.warning("recipe_start_has_feature_json", path=str(recipe_dir))
                return None
        return meta
