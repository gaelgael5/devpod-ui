"""profiles.image : image de base du devcontainer portée par le profil.

Vide = image par défaut du portail (mcr.microsoft.com/devcontainers/base:ubuntu).
Permet aux profils de la galerie de partir d'une image outillée et de ne
nécessiter des recettes que pour les manques de l'image de base.

Revision ID: 048
Revises: 047
Create Date: 2026-07-05
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "048"
down_revision: str | None = "047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("image", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("profiles", "image")
