"""session_durations : durées de session éditables en admin (idle glissant + plafond absolu).

Ajoute `session_max_age` et `session_absolute_max_age` (secondes) à `global_config`.
0 = hériter du défaut settings/env ; une valeur > 0 (posée via l'admin) prime, sans
redémarrage. Cf. config/store.effective_session_* + auth/rbac + app._PortalSessionMiddleware.

Revision ID: 073
Revises: 072
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "073"
down_revision: str | None = "072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "global_config",
        sa.Column("session_max_age", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "global_config",
        sa.Column("session_absolute_max_age", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("global_config", "session_absolute_max_age")
    op.drop_column("global_config", "session_max_age")
