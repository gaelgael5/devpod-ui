"""Quels changements de `WorkspaceSpec` imposent de RECRÉER le conteneur.

Éditer la configuration d'un workspace existant ne suffit pas toujours : certains
champs ne sont lus qu'à la CONSTRUCTION du devcontainer (features des recettes,
image du profil, `runArgs` mémoire, port/clé SSH du composant `ssh-access`). Les
modifier sur un workspace déjà bâti ne produit aucun effet tant que l'image n'est
pas reconstruite — le pire des cas étant l'utilisateur qui croit sa recette
installée alors qu'elle n'est nulle part.

Trois niveaux, du moins au plus coûteux :

- **immédiat**  : la valeur est lue à chaud (groupes, keep_active) ;
- **restart**   : rejoué à chaque `up` (agents, recettes de démarrage, sources
  additionnelles clonées post-readiness) — un stop/start suffit ;
- **recreate**  : entre dans le devcontainer.json, donc dans l'image.

Source de vérité unique, partagée par l'API d'édition et l'UI : c'est elle qui
décide du bandeau d'avertissement affiché après enregistrement.
"""

from __future__ import annotations

from typing import Any

# Champs injectés dans le devcontainer.json (cf. devpod/service._write_devcontainer) :
# les toucher n'a d'effet qu'après reconstruction de l'image.
RECREATE_FIELDS: frozenset[str] = frozenset(
    {
        "recipes",  # features du devcontainer
        "profile",  # image de base + customizations vscode
        "memory_limit",  # runArgs --memory
        "recipe_volumes",  # mounts
        "host",  # le conteneur vit sur un AUTRE nœud
        "source",  # dépôt cloné à la création
        "devcontainer_path",
        "template",
    }
)

# Champs rejoués à chaque `up` (post-readiness ou args de lancement) : un
# stop/start les applique, inutile de reconstruire.
RESTART_FIELDS: frozenset[str] = frozenset(
    {
        "branch",
        "git_credential",
        "extra_sources",
        "agents",
        "start_recipes",
        "init_recipes",
        "default_start",
        "env",
        "ide",
        "idle_timeout",
        "expose",
        "ssh_key",
    }
)


def _normalize(value: Any) -> Any:
    """Forme comparable d'une valeur de spec.

    Les listes de recettes sont comparées comme des ENSEMBLES : leur ordre n'entre
    pas dans le devcontainer (il est recalculé par le tri topologique des
    dépendances), donc un simple réagencement ne doit pas réclamer un recreate.
    Les modèles Pydantic (profile, extra_sources) sont réduits à leur dump.
    """
    if isinstance(value, list):
        items = [_normalize(v) for v in value]
        if all(isinstance(v, str) for v in items):
            return sorted(items)
        return items
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def changed_fields(old: Any, new: Any, fields: frozenset[str] | None = None) -> list[str]:
    """Champs dont la valeur diffère entre deux specs (triés, comparaison normalisée)."""
    names = fields if fields is not None else frozenset(type(new).model_fields)
    out = [
        name
        for name in names
        if _normalize(getattr(old, name, None)) != _normalize(getattr(new, name, None))
    ]
    return sorted(out)


def requires_recreate(old: Any, new: Any) -> list[str]:
    """Champs modifiés qui n'auront d'effet qu'après recréation du conteneur."""
    return changed_fields(old, new, RECREATE_FIELDS)


def requires_restart(old: Any, new: Any) -> list[str]:
    """Champs modifiés appliqués au prochain `up` (stop/start suffit)."""
    return changed_fields(old, new, RESTART_FIELDS)


def added_recipes(old: Any, new: Any) -> list[str]:
    """Recettes AJOUTÉES (le cas cité en exemple : elles imposent un recreate).

    Distingué du simple « recipes a changé » pour que l'UI puisse être explicite :
    « claude-code, python ajoutées — recréez pour les installer » est autrement
    plus actionnable que « la configuration a changé »."""
    before = set(getattr(old, "recipes", []) or [])
    return sorted(set(getattr(new, "recipes", []) or []) - before)
