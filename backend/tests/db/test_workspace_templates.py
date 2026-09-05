"""Le CRUD des templates de workspace, contre le vrai schéma (migration 135)."""

from __future__ import annotations

from portal.config.models import WorkspaceTemplate, WorkspaceTemplateSpec
from portal.db.workspace_templates import (
    delete_template,
    get_template,
    list_templates,
    upsert_template,
)


def _template(slug: str, *, published: bool = False) -> WorkspaceTemplate:
    return WorkspaceTemplate(
        slug=slug,
        label=slug.title(),
        published=published,
        spec=WorkspaceTemplateSpec(recipes=["python"], ssh_key=True, memory_limit="8g"),
    )


async def test_upsert_lit_et_reecrit_le_preset(db_conn) -> None:
    await upsert_template(_template("python-ia", published=True), db_conn)
    lu = await get_template("python-ia", db_conn)
    assert lu is not None
    assert lu.spec.recipes == ["python"]
    assert lu.spec.ssh_key is True

    # Upsert = mise à jour, pas doublon.
    modifie = lu.model_copy(update={"label": "Python + IA v2"})
    await upsert_template(modifie, db_conn)
    assert len(await list_templates(db_conn)) == 1
    relu = await get_template("python-ia", db_conn)
    assert relu is not None and relu.label == "Python + IA v2"


async def test_la_galerie_filtre_les_brouillons(db_conn) -> None:
    await upsert_template(_template("publie", published=True), db_conn)
    await upsert_template(_template("brouillon", published=False), db_conn)
    galerie = await list_templates(db_conn, published_only=True)
    assert [t.slug for t in galerie] == ["publie"]
    assert len(await list_templates(db_conn)) == 2


async def test_suppression_idempotente(db_conn) -> None:
    await upsert_template(_template("ephemere"), db_conn)
    assert await delete_template("ephemere", db_conn) is True
    assert await delete_template("ephemere", db_conn) is False
    assert await get_template("ephemere", db_conn) is None
