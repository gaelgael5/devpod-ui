"""Ajout de cookie_domain à global_config.

Domaine du cookie de session configurable depuis /admin/network.
Obligatoire quand portail (dev.yoops.org) et proxy VS Code (vs-dev.yoops.org)
n'ont qu'un ancêtre commun (yoops.org) — sinon le cookie n'est pas transmis à
vs-dev.yoops.org et le forward_auth échoue.

Revision ID: 034
Revises: 033
Create Date: 2026-06-28
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "034"
down_revision: str | None = "033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "global_config",
        sa.Column("cookie_domain", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("global_config", "cookie_domain")
