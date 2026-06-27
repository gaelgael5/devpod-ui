"""Galerie docker-compose : templates, déploiements, logs.

Revision ID: 030
Revises: 029
Create Date: 2026-06-27
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "030"
down_revision: str | None = "029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "compose_template",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags", ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("compose_content", sa.Text(), nullable=False),
        sa.Column("parameters", JSONB(), nullable=False, server_default="[]"),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "compose_deployment",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "template_id",
            sa.Text(),
            sa.ForeignKey("compose_template.id"),
            nullable=False,
        ),
        sa.Column("template_version", sa.Text(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("owner_login", sa.Text(), nullable=False),
        sa.Column("env_values", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "host_ports", ARRAY(sa.Integer()), nullable=False, server_default="{}"
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="created"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "compose_deployment_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("deployment_id", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_deployment_node", "compose_deployment", ["node_id"])
    op.create_index("idx_deployment_owner", "compose_deployment", ["owner_login"])
    op.create_index(
        "idx_deployment_ports",
        "compose_deployment",
        ["host_ports"],
        postgresql_using="gin",
    )
    op.create_index(
        "idx_template_tags", "compose_template", ["tags"], postgresql_using="gin"
    )
    op.create_index(
        "idx_deployment_log_dep", "compose_deployment_log", ["deployment_id"]
    )


def downgrade() -> None:
    op.drop_table("compose_deployment_log")
    op.drop_table("compose_deployment")
    op.drop_table("compose_template")
