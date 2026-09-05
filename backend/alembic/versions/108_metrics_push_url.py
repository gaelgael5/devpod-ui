"""URL de push des metriques machine (TSDB), a cote de celle des logs.

La chaine d'observabilite ne couvrait que les logs (Alloy -> Loki). Le
collecteur de metriques est son miroir cote series temporelles et pousse en
`remote_write` vers un TSDB. Comme `loki_push_url`, l'URL derive (IP du
collecteur central) : elle se declare en configuration et le portail l'injecte
au deploiement, pour que le resync puisse la realigner sur les collecteurs deja
installes.

Ajout CONDITIONNEL : une base deja deployee peut avoir vu passer d'autres
chemins de migration.

Revision ID: 108
Revises: 107
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "108"
down_revision: str | None = "107"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "global_config"
_COL = "logs_metrics_push_url"


def _colonnes() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {c["name"] for c in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    if _COL not in _colonnes():
        op.add_column(
            _TABLE,
            sa.Column(_COL, sa.Text(), nullable=False, server_default=""),
        )


def downgrade() -> None:
    if _COL in _colonnes():
        op.drop_column(_TABLE, _COL)
