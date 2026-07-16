"""host_docker_cert : certificat client mTLS associé à un host docker-tls.

Ajoute `docker_cert_slug` à `hosts` : référence (slug) vers une entrée tls-*
du gestionnaire de certificats (`harpo_certificates`). Vide = le host utilise
le répertoire partagé `client_cert_path` (comportement historique).

Revision ID: 071
Revises: 070
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "071"
down_revision: str | None = "070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hosts",
        sa.Column("docker_cert_slug", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("hosts", "docker_cert_slug")
