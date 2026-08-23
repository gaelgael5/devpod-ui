"""Horodatage PAR mesure sur `host_disk` (cadences distinctes).

Disque, mémoire et CPU ne sont plus relevés au même rythme (1 h / 5 min / 30 s) :
un `measured_at` unique ferait passer une mesure disque vieille d'une heure pour
aussi fraîche que le CPU relevé il y a 30 s. Chaque famille porte donc sa propre
date ; `measured_at` reste la date de la dernière sonde, quelle qu'elle soit.

Revision ID: 103
Revises: 102
Create Date: 2026-08-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "103"
down_revision: str | None = "102"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for col in ("disk_measured_at", "mem_measured_at", "cpu_measured_at"):
        op.add_column("host_disk", sa.Column(col, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for col in ("disk_measured_at", "mem_measured_at", "cpu_measured_at"):
        op.drop_column("host_disk", col)
