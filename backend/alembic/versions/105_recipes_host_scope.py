"""Portée host des recettes : `host_scope`, `host_usages`, `preconditions`.

Ces champs ont été ajoutés à `RecipeMeta` pour les recettes de MACHINE (ticket
76a74588) mais jamais persistés : la table les ignorait, `_row_to_meta` ne les
relisait pas, et une recette déclarant `scope: host` dans son YAML revenait de
la base en `workspace`. Elle n'apparaissait donc dans aucune liste de machine —
symptôme observé : « aucune recette du catalogue ne vise la famille de cette
machine » alors que la recette était bien au catalogue.

Le nom `host_scope` plutôt que `scope` est délibéré : la colonne `scope` existe
déjà sur cette table et désigne tout autre chose — la portée du CATALOGUE
(partagé / propre à un utilisateur). Deux notions distinctes ne doivent pas
porter le même nom dans la même table.

Ajout CONDITIONNEL : la table existe depuis la migration 007, et rien ne
garantit l'état des bases déjà déployées.

Revision ID: 105
Revises: 104
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "105"
down_revision: str | None = "104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLONNES = {
    # `workspace` par défaut : tout le catalogue existant garde son sens, aucune
    # recette ne devient applicable à une machine par migration.
    "host_scope": sa.Column("host_scope", sa.Text(), nullable=False, server_default="workspace"),
    "host_usages": sa.Column("host_usages", ARRAY(sa.Text()), nullable=False, server_default="{}"),
    "preconditions": sa.Column("preconditions", JSONB(), nullable=False, server_default="[]"),
}


def _existantes() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {c["name"] for c in inspector.get_columns("recipes")}


def upgrade() -> None:
    presentes = _existantes()
    for nom, colonne in _COLONNES.items():
        if nom not in presentes:
            op.add_column("recipes", colonne)


def downgrade() -> None:
    presentes = _existantes()
    for nom in _COLONNES:
        if nom in presentes:
            op.drop_column("recipes", nom)
