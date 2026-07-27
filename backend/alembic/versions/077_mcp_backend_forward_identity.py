"""mcp_backend.forward_identity : propagation on-behalf-of de l'identité humaine.

false par défaut (comportement historique : le backend ne voit que la clé). true =
le portail ajoute aux appels sortants les en-têtes signés x-portal-actor* (cf.
mcp/obo) portant l'utilisateur de la session. Réservé aux backends first-party de
confiance qui vérifient la signature (docflow, rag, workflow).

Revision ID: 077
Revises: 076
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "077"
down_revision: str | None = "076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_backend",
        sa.Column("forward_identity", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("mcp_backend", "forward_identity")
