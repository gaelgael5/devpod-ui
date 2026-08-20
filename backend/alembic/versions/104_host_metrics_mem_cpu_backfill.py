"""Rattrapage : colonnes mémoire/CPU de `host_disk` absentes des bases existantes.

Erreur d'origine : les colonnes `mem_*` / `cpu_*` ont été ajoutées **à l'intérieur
du `create_table` de la migration 102 après que celle-ci avait déjà été appliquée**.
Alembic marque 102 comme jouée et ne la rejoue jamais : sur toute base où 102 est
passée dans sa forme initiale, ces colonnes n'existent pas — le portail échouait
alors en `UndefinedColumnError` à chaque lecture de `host_disk`, et l'UI, qui
dégrade silencieusement, n'affichait simplement aucune métrique.

Une migration déjà appliquée ne se modifie pas : on rattrape par une révision.

Ajout CONDITIONNEL (inspection du schéma) pour couvrir les deux cas :
- base existante, 102 jouée sans les colonnes → elles sont ajoutées ici ;
- base neuve, 102 jouée avec les colonnes → rien à faire, on saute.

Revision ID: 104
Revises: 103
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "104"
down_revision: str | None = "103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS: list[tuple[str, sa.types.TypeEngine]] = [
    ("mem_total_bytes", sa.BigInteger()),
    ("mem_used_bytes", sa.BigInteger()),
    ("mem_pct", sa.Integer()),
    ("cpu_pct", sa.Integer()),
    ("cpu_cores", sa.Integer()),
]


def _existing_columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {c["name"] for c in inspector.get_columns("host_disk")}


def upgrade() -> None:
    present = _existing_columns()
    for name, type_ in _COLUMNS:
        if name not in present:
            op.add_column("host_disk", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    present = _existing_columns()
    for name, _type in _COLUMNS:
        if name in present:
            op.drop_column("host_disk", name)
