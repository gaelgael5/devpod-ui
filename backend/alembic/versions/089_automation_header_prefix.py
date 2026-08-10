"""Headers d'automate enrichis : value_prefix / required / enabled + XOR relâché.

Aligne sur docflow : préfixe de valeur (« Bearer »), en-tête requis (auth du
contrat) et actif ; le CHECK value XOR secret est retiré pour autoriser un stub
d'en-tête d'auth auto-ajouté avant que le secret ne soit choisi.

Revision ID: 089
Revises: 088
Create Date: 2026-08-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "089"
down_revision: str | None = "088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "automation_header",
        sa.Column("value_prefix", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "automation_header",
        sa.Column("required", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "automation_header",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.drop_constraint(
        "ck_automation_header_value_xor_secret", "automation_header", type_="check"
    )


def downgrade() -> None:
    op.create_check_constraint(
        "ck_automation_header_value_xor_secret",
        "automation_header",
        "(value IS NULL) <> (secret_ref IS NULL)",
    )
    op.drop_column("automation_header", "enabled")
    op.drop_column("automation_header", "required")
    op.drop_column("automation_header", "value_prefix")
