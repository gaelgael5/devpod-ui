"""Occupation disque, mémoire et charge CPU des hosts : table `host_disk`.

Alimentée par la sonde horaire (`nodes/disk.py`), lue par `node_list` et
l'agrégat sessions. Sert aussi l'alerte « host presque plein » de la vue
workspaces. Un host jamais sondé n'a PAS de ligne : l'absence se lit
« inconnu », jamais « 0 % ».

Revision ID: 102
Revises: 101
Create Date: 2026-08-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "102"
down_revision: str | None = "101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "host_disk",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("total_bytes", sa.BigInteger(), nullable=True),
        sa.Column("used_bytes", sa.BigInteger(), nullable=True),
        sa.Column("avail_bytes", sa.BigInteger(), nullable=True),
        sa.Column("used_pct", sa.Integer(), nullable=True),
        sa.Column("mem_total_bytes", sa.BigInteger(), nullable=True),
        sa.Column("mem_used_bytes", sa.BigInteger(), nullable=True),
        sa.Column("mem_pct", sa.Integer(), nullable=True),
        sa.Column("cpu_pct", sa.Integer(), nullable=True),
        sa.Column("cpu_cores", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "measured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("host_disk")
