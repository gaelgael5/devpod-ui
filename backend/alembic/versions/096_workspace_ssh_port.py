"""Port SSH par workspace : colonne `workspace_status.ssh_port`.

Spec 18 (Termix multi-node, T1) : chaque workspace expose un sshd publié sur l'IP
du node via un port dédié, alloué dans la plage 50000-59999 par un second
`PortRegistry` (distinct du `host_port` openvscode). Nullable : les workspaces
sans accès SSH publié n'ont pas de port.

Revision ID: 096
Revises: 095
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "096"
down_revision: str | None = "095"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workspace_status", sa.Column("ssh_port", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("workspace_status", "ssh_port")
