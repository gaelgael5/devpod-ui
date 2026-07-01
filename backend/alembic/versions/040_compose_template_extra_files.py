"""Ajoute extra_files JSONB sur compose_template pour les fichiers compagnons des templates builtin.

Revision ID: 040
Revises: 039
Create Date: 2026-07-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "040"
down_revision: str | None = "039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "compose_template",
        sa.Column("extra_files", JSONB, nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("compose_template", "extra_files")
