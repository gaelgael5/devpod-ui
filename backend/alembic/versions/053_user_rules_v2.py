"""user_rules v2 : conditions en ET, actions multiples, enchaînement.

Le couple sonde/condition/action unique devient deux listes JSONB :
`conditions` = [{service_id, tool, args, path, operator, value}] (ET logique),
`actions` = [{service_id, tool, args}] (ordonnées). `next_rule_id` référence la
règle jouée à la suite quand les actions ont couru (SET NULL si supprimée).
Les lignes existantes sont converties (1 condition, 1 action). Les service_id
passent en JSONB : plus de FK SET NULL — un service supprimé est détecté à
l'exécution (règle signalée inopérante).

Revision ID: 053
Revises: 052
Create Date: 2026-07-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "053"
down_revision: str | None = "052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_rules",
        sa.Column("conditions", JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "user_rules",
        sa.Column("actions", JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "user_rules",
        sa.Column(
            "next_rule_id",
            sa.Text(),
            sa.ForeignKey("user_rules.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE user_rules SET
          conditions = jsonb_build_array(jsonb_build_object(
            'service_id', probe_service_id,
            'tool', probe_tool,
            'args', probe_args,
            'path', condition_path,
            'operator', condition_operator,
            'value', condition_value)),
          actions = jsonb_build_array(jsonb_build_object(
            'service_id', action_service_id,
            'tool', action_tool,
            'args', action_args))
        """
    )
    op.drop_constraint("ck_user_rules_operator", "user_rules", type_="check")
    for col in (
        "probe_service_id",
        "probe_tool",
        "probe_args",
        "condition_path",
        "condition_operator",
        "condition_value",
        "action_service_id",
        "action_tool",
        "action_args",
    ):
        op.drop_column("user_rules", col)


def downgrade() -> None:
    raise NotImplementedError("053 restructure user_rules — downgrade non supporté")
