"""Tour 10 : table node_certificates (Groupe 4 — dépend de hosts).

Revision ID: 010
Revises: 009
Create Date: 2026-06-17
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "node_certificates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("node_name", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("cert_pem", sa.Text(), nullable=False),
        sa.Column("serial_number", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "signed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("node_name", name="uq_node_certificates_node_name"),
    )
    op.create_index(
        "idx_node_certificates_expires",
        "node_certificates",
        ["expires_at"],
        postgresql_where="revoked_at IS NULL",
    )


def downgrade() -> None:
    op.drop_index("idx_node_certificates_expires", table_name="node_certificates")
    op.drop_table("node_certificates")
