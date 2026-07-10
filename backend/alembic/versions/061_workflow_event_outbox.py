"""Outbox transactionnel pour le relais d'events vers le workflow.

Le relais egress était **best-effort** : l'écouteur du bus signait et postait
immédiatement, sans file ni retry — un workflow indisponible perdait l'event.
Cette table sert de **tampon transactionnel** : l'écouteur du bus n'y fait plus
qu'insérer l'enveloppe (mêmes octets à signer et à poster), et un worker de fond
lit les entrées dues, les pousse (POST signé HMAC) et applique retry/backoff.

Revision ID: 061
Revises: 060
Create Date: 2026-07-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "061"
down_revision: str | None = "060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_event_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("event_code", sa.Text(), nullable=False),
        # Octets exacts sérialisés (compacts, ensure_ascii=False) — signés ET postés.
        sa.Column("raw_body", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_workflow_event_outbox_due",
        "workflow_event_outbox",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_workflow_event_outbox_due", table_name="workflow_event_outbox")
    op.drop_table("workflow_event_outbox")
