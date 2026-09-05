"""Plafond memoire par workspace porte par le noeud : hosts.max_memory.

Variable reservee `max_memory` (fiche 1dae864d) : la memoire maximale qu'un
workspace Docker peut se voir allouer sur ce noeud. Meme mecanique que
`capacity_workspaces` — declaree sur le type d'hyperviseur, valuee par le profil
de host, recopiee ici au provisionnement, puis lue a la creation/edition d'un
workspace pour refuser une demande superieure. Vide = non renseigne : pas de
bornage, comportement actuel inchange.

Revision ID: 132
Revises: 131
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "132"
down_revision: str | None = "131"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hosts",
        sa.Column("max_memory", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("hosts", "max_memory")
