"""Moteur d'automates (port docflow) : contrats OpenAPI + automation & co.

Contrats OpenAPI globaux réutilisables + automates qui consomment le journal
`app_event` par curseur et appellent une opération d'un contrat. Anti-rejeu par
index unique partiel sur les runs automatiques ; en-têtes value XOR secret_ref ;
portées multi-workspaces ; ordre d'évaluation + stop_chain.

Revision ID: 087
Revises: 086
Create Date: 2026-08-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "087"
down_revision: str | None = "086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "openapi_contract",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("version", sa.Text(), nullable=False, server_default=""),
        sa.Column("raw_spec", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "automation",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stop_chain", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("event_types", sa.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("delay_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "contract_ref",
            sa.Text(),
            sa.ForeignKey("openapi_contract.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("operation_id", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("http_method", sa.Text(), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("idx_automation_position", "automation", ["position"])

    op.create_table(
        "automation_scope",
        sa.Column(
            "automation_id",
            sa.Text(),
            sa.ForeignKey("automation.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workspace", sa.Text(), nullable=False),
        sa.UniqueConstraint("automation_id", "workspace", name="uq_automation_scope"),
    )

    op.create_table(
        "automation_header",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "automation_id",
            sa.Text(),
            sa.ForeignKey("automation.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("secret_ref", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "(value IS NULL) <> (secret_ref IS NULL)",
            name="ck_automation_header_value_xor_secret",
        ),
    )
    op.create_index("idx_automation_header_by_automation", "automation_header", ["automation_id"])

    op.create_table(
        "automation_cursor",
        sa.Column(
            "automation_id",
            sa.Text(),
            sa.ForeignKey("automation.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("last_seq", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "automation_run",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "automation_id",
            sa.Text(),
            sa.ForeignKey("automation.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_seq", sa.BigInteger(), nullable=False),
        sa.Column("dedup_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("request_preview", sa.Text(), nullable=True),
        sa.Column("response_preview", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("manual", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "uq_automation_run_auto_dedup",
        "automation_run",
        ["automation_id", "dedup_key"],
        unique=True,
        postgresql_where=sa.text("manual = false"),
    )
    op.create_index("idx_automation_run_history", "automation_run", ["automation_id", "created_at"])


def downgrade() -> None:
    op.drop_table("automation_run")
    op.drop_table("automation_cursor")
    op.drop_table("automation_header")
    op.drop_table("automation_scope")
    op.drop_index("idx_automation_position", table_name="automation")
    op.drop_table("automation")
    op.drop_table("openapi_contract")
