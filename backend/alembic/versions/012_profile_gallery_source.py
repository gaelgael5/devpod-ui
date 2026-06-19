"""Colonne gallery_source sur la table profiles.

Revision ID: 012
Revises: 011
Create Date: 2026-06-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("gallery_source", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("profiles", "gallery_source")
