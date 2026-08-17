"""Quels changements de config imposent de RECRÉER le conteneur.

Enjeu : un champ qui n'entre que dans le devcontainer.json (recettes, profil,
mémoire) n'a AUCUN effet sur un workspace déjà bâti. Se tromper ici, c'est
laisser l'utilisateur croire sa recette installée alors qu'elle n'est nulle part.
"""

from __future__ import annotations

from portal.config.models import ProfileRef, SourceSpec, WorkspaceSpec
from portal.devpod.spec_changes import (
    added_recipes,
    requires_recreate,
    requires_restart,
)


def spec(**over: object) -> WorkspaceSpec:
    base: dict[str, object] = {"name": "demo", "source": "github.com/org/demo"}
    return WorkspaceSpec.model_validate({**base, **over})


def test_no_change_requires_nothing() -> None:
    a = spec(recipes=["python"])
    assert requires_recreate(a, spec(recipes=["python"])) == []
    assert requires_restart(a, spec(recipes=["python"])) == []


def test_adding_a_recipe_requires_recreate() -> None:
    """Le cas cité en exemple : une recette ajoutée est une feature devcontainer."""
    before = spec(recipes=["python"])
    after = spec(recipes=["python", "claude-code"])
    assert requires_recreate(before, after) == ["recipes"]
    assert added_recipes(before, after) == ["claude-code"]


def test_removing_a_recipe_also_requires_recreate() -> None:
    before = spec(recipes=["python", "claude-code"])
    after = spec(recipes=["python"])
    assert requires_recreate(before, after) == ["recipes"]
    # Retrait ≠ ajout : rien à signaler comme « à installer ».
    assert added_recipes(before, after) == []


def test_reordering_recipes_is_not_a_change() -> None:
    """L'ordre est recalculé par le tri topologique des dépendances : le
    réagencer ne change pas l'image, donc n'impose pas de recréation."""
    before = spec(recipes=["python", "tmux"])
    after = spec(recipes=["tmux", "python"])
    assert requires_recreate(before, after) == []
    assert added_recipes(before, after) == []


def test_profile_memory_and_host_require_recreate() -> None:
    base = spec()
    assert requires_recreate(base, spec(profile=ProfileRef(scope="shared", slug="py"))) == [
        "profile"
    ]
    assert requires_recreate(base, spec(memory_limit="2g")) == ["memory_limit"]
    assert requires_recreate(base, spec(host="node-2")) == ["host"]
    assert requires_recreate(base, spec(source="github.com/org/autre")) == ["source"]


def test_restart_only_fields_do_not_require_recreate() -> None:
    """Rejoués à chaque `up` : un stop/start suffit, reconstruire serait abusif."""
    base = spec()
    for field, value in (
        ("branch", "feature/x"),
        ("agents", ["claude"]),
        ("start_recipes", ["serve"]),
        ("init_recipes", ["seed"]),
        ("env", {"A": "1"}),
        ("ssh_key", True),
        ("extra_sources", [SourceSpec(url="github.com/org/lib")]),
    ):
        after = spec(**{field: value})
        assert requires_recreate(base, after) == [], f"{field} ne doit pas exiger un recreate"
        assert field in requires_restart(base, after), f"{field} doit exiger un restart"


def test_groups_and_keep_active_need_neither() -> None:
    """Lus à chaud : ni reconstruction ni redémarrage."""
    base = spec()
    for field, value in (("groups", ["team"]), ("keep_active", True)):
        after = spec(**{field: value})
        assert requires_recreate(base, after) == []
        assert requires_restart(base, after) == []


def test_several_changes_are_all_reported_sorted() -> None:
    before = spec(recipes=["python"])
    after = spec(recipes=["python", "tmux"], memory_limit="4g", host="node-2")
    assert requires_recreate(before, after) == ["host", "memory_limit", "recipes"]
