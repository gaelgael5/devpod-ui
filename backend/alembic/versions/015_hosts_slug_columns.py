"""hosts: remplace key_path/public_key/ci_password par slugs harpo_*.

Revision ID: 015
Revises: 014
Create Date: 2026-06-20
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Suppression des colonnes remplacées
    op.drop_column("hosts", "key_path")
    op.drop_column("hosts", "public_key")
    # ci_password n'était pas dans la migration initiale (001) — IF EXISTS pour compatibilité
    op.execute(sa.text("ALTER TABLE hosts DROP COLUMN IF EXISTS ci_password"))

    # Ajout des nouvelles colonnes slug + préférences stockage
    op.add_column(
        "hosts",
        sa.Column("ci_password_secret_slug", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "hosts",
        sa.Column("host_cert_slug", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "hosts",
        sa.Column("storage_type", sa.Text(), nullable=False, server_default="local"),
    )
    op.add_column(
        "hosts",
        sa.Column("vault_identifier", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("hosts", "vault_identifier")
    op.drop_column("hosts", "storage_type")
    op.drop_column("hosts", "host_cert_slug")
    op.drop_column("hosts", "ci_password_secret_slug")

    op.add_column(
        "hosts",
        sa.Column("ci_password", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "hosts",
        sa.Column("public_key", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "hosts",
        sa.Column("key_path", sa.Text(), nullable=False, server_default=""),
    )
