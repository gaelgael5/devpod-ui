"""test_host_share : partage d'une VM de test à d'autres workspaces.

Ajoute `shared_from_workspace` à `workspace_test_hosts` : NULL = ligne du
workspace PROPRIÉTAIRE (celui qui a créé la VM et en pilote le cycle de vie) ;
non-NULL = ligne de PARTAGE, sa valeur étant le nom du workspace propriétaire
d'origine. Le workspace cible obtient l'accès SSH (`ssh testN`) sans contrôle du
cycle de vie de la VM.

Revision ID: 069
Revises: 068
Create Date: 2026-07-15
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "069"
down_revision: str | None = "068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspace_test_hosts",
        sa.Column("shared_from_workspace", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspace_test_hosts", "shared_from_workspace")
