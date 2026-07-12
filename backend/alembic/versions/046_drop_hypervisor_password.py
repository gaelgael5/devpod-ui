"""hypervisors.password : supprime le champ mot de passe en clair (bug 021).

Champ passif — l'auth SSH réelle est par clé (BatchMode=yes), aucun code ne
consomme cette valeur. Le conserver revient à stocker et renvoyer un secret
en clair sans aucun usage.

Revision ID: 046
Revises: 045
Create Date: 2026-07-04
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "046"
down_revision: str | None = "045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("hypervisors", "password")


def downgrade() -> None:
    op.add_column(
        "hypervisors",
        sa.Column("password", sa.Text(), nullable=False, server_default=""),
    )
