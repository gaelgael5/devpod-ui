"""Aller-retour en base des champs de portée machine.

Le defaut qui a motive ce test : `RecipeMeta` portait `scope`, `host_usages` et
`preconditions`, mais la persistance les ignorait. Une recette declarant
`scope: host` revenait de la base en `workspace` — invisible sur toute machine,
alors qu'elle figurait bien au catalogue.
"""

from __future__ import annotations

from portal.db.recipes import _row_to_meta
from portal.recipes.models import RecipeMeta


def _ligne(**extra: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "android-emulator",
        "key": "fe46f7ec-33f7-4252-b29c-cf224b8cd1af",
        "type": "install",
        "version": "1.0.0",
        "description": "",
        "options": {},
        "requires_secrets": [],
        "installs_after": [],
    }
    base.update(extra)
    return base


def test_relit_la_portee_host() -> None:
    meta = _row_to_meta(_ligne(host_scope="host", host_usages=["tests"]))

    assert meta.scope == "host"
    assert meta.applies_to_host("tests") is True


def test_relit_les_preconditions() -> None:
    meta = _row_to_meta(
        _ligne(
            host_scope="host",
            host_usages=["tests"],
            preconditions=[{"path_exists": "/dev/kvm"}, {"disk_free_gb": 30}],
        )
    )

    assert len(meta.preconditions) == 2
    assert meta.preconditions[0].path_exists == "/dev/kvm"


def test_ligne_ancienne_reste_une_recette_de_workspace() -> None:
    """Base anterieure a la migration : aucune colonne. Le catalogue existant ne
    doit pas devenir applicable aux machines par accident."""
    meta = _row_to_meta(_ligne())

    assert meta.scope == "workspace"
    assert meta.applies_to_host("tests") is False


def test_colonnes_nulles_traitees_comme_absentes() -> None:
    meta = _row_to_meta(_ligne(host_scope=None, host_usages=None, preconditions=None))

    assert meta.scope == "workspace"
    assert meta.host_usages == []


def test_aller_retour_complet() -> None:
    """Ce que `upsert_recipe_db` ecrit doit se relire a l'identique."""
    origine = RecipeMeta.model_validate(
        {
            "id": "android-emulator",
            "scope": "host",
            "host_usages": ["tests", "ressources"],
            "preconditions": [{"path_exists": "/dev/kvm"}, {"arch": "x86_64"}],
        }
    )
    # Miroir des colonnes ecrites par `upsert_recipe_db`.
    ligne = _ligne(
        key=origine.key,
        host_scope=origine.scope,
        host_usages=list(origine.host_usages),
        preconditions=[p.model_dump() for p in origine.preconditions],
    )

    relue = _row_to_meta(ligne)

    assert relue.scope == origine.scope
    assert relue.host_usages == origine.host_usages
    assert len(relue.preconditions) == len(origine.preconditions)
    assert relue.applies_to_host("ressources") is True
