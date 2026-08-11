"""Arbre de règle des automates : colonne `tree` JSONB, colonnes plates supprimées.

Une règle devient un arbre de blocs récursifs {filtre ET/OU imbriqué → appels
nommés → blocs enfants} rangé dans `automation.tree` (schéma automations/tree.py).
Les colonnes plates « un filtre + un appel » (contract_ref, operation_id, url,
http_method, body_template, filter_*) disparaissent — décision assumée : les
règles existantes repartent d'un arbre vide et sont re-saisies dans le nouvel
éditeur (elles restent listées avec label/slug/triggers/headers/curseur intacts).

Ajoute aussi `automation_run.trace` (JSONB) : trace structurée du parcours de
l'arbre, un item par nœud exécuté (filtres évalués, appels, statuts).

Revision ID: 094
Revises: 093
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "094"
down_revision: str | None = "093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DROPPED = (
    "filter_expected",
    "filter_operator",
    "filter_jsonpath",
    "filter_body",
    "filter_method",
    "filter_url",
    "filter_operation_id",
    "filter_contract_ref",
    "body_template",
    "http_method",
    "url",
    "operation_id",
    "contract_ref",
)


def upgrade() -> None:
    op.add_column(
        "automation",
        sa.Column(
            "tree",
            JSONB(),
            nullable=False,
            server_default='{"version": 1, "blocks": []}',
        ),
    )
    for col in _DROPPED:
        op.drop_column("automation", col)
    op.add_column("automation_run", sa.Column("trace", JSONB(), nullable=True))


def downgrade() -> None:
    # Les données plates sont perdues à l'upgrade : le downgrade recrée les
    # colonnes nullable (sans FK ni NOT NULL) pour redonner un schéma utilisable.
    op.drop_column("automation_run", "trace")
    for col in reversed(_DROPPED):
        op.add_column("automation", sa.Column(col, sa.Text(), nullable=True))
    op.drop_column("automation", "tree")
