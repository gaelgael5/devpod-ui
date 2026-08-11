"""En-têtes d'automate déplacés dans l'arbre : suppression de `automation_header`.

Les en-têtes ne sont plus partagés au niveau règle : chaque appel et chaque
feuille de filtre de `automation.tree` porte ses propres en-têtes (pré-remplis
depuis l'opération du contrat). La table `automation_header` disparaît — comme
la 094 a déjà vidé les règles (arbres à re-saisir), aucune donnée à migrer.

Revision ID: 095
Revises: 094
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "095"
down_revision: str | None = "094"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("automation_header")


def downgrade() -> None:
    op.create_table(
        "automation_header",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "automation_id",
            sa.Text(),
            sa.ForeignKey("automation.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("secret_ref", sa.Text(), nullable=True),
        sa.Column("value_prefix", sa.Text(), nullable=False, server_default=""),
        sa.Column("required", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index(
        "idx_automation_header_by_automation", "automation_header", ["automation_id"]
    )
