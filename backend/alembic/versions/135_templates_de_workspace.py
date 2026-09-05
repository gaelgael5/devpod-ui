"""Templates de création de workspace — galerie admin.

Un template fige recettes, agents, profil devcontainer, limite mémoire et clef
SSH ; l'utilisateur ne saisit que le nom et le repo git. Le preset vit en JSONB
(`spec`, validé par pydantic à la lecture comme à l'écriture) : ajouter un
champ au preset ne demande pas de migration.

Revision ID: 135
Revises: 134
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "135"
down_revision: str | Sequence[str] | None = "134"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_templates",
        sa.Column("slug", sa.Text(), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        # Visibilite utilisateur : un brouillon d'admin n'apparait jamais dans
        # le dialogue de creation.
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("spec", sa.dialects.postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("workspace_templates")
